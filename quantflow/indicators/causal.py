"""Causal / anti-lookahead helpers for indicator & signal pipelines.

Rules of thumb (W17 AF-4 and later):
- Rolling windows must use only past and *current* bar inputs.
- Decision series used for trading should be ``shift(1)`` so bar *t* trade
  uses information known at close of *t-1* (or open of *t*, depending on
  execution model). Dual-MA overlay already shifts signals one bar.
- Never use ``shift(-k)`` (k>0) — that pulls future values into the present.
- Prefer ``assert_series_causal`` / ``assert_frame_causal`` in unit tests for
  every new factor.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


def shift_for_trade(signal: pd.Series, bars: int = 1) -> pd.Series:
    """Delay a signal so it is only actionable on subsequent bars.

    ``bars=1`` is the standard no-lookahead execution lag for OHLC close signals.
    """
    if bars < 0:
        raise ValueError("shift_for_trade bars must be >= 0 (negative would look ahead)")
    if bars == 0:
        return signal.astype(float)
    return signal.astype(float).shift(bars)


def assert_series_causal(
    compute_fn: Callable[[pd.DataFrame], pd.Series],
    df: pd.DataFrame,
    *,
    min_prefix: int = 50,
    rtol: float = 1e-9,
    atol: float = 1e-9,
    name: str = "series",
) -> None:
    """Fail if truncating the DataFrame changes earlier factor values.

    Computes ``full = f(df)`` and ``prefix = f(df.iloc[:k])`` for several k.
    Values on the overlapping index (excluding a small warm-up tail of the
    prefix) must match. A look-ahead factor that uses future rows will change
    historical values when the future is removed.
    """
    if len(df) < min_prefix + 10:
        raise ValueError(f"need at least {min_prefix + 10} rows for causal check")

    full = compute_fn(df)
    if not isinstance(full, pd.Series):
        raise TypeError(f"{name}: compute_fn must return Series, got {type(full)}")
    full = full.astype(float)

    check_points = sorted(
        {
            min_prefix,
            max(min_prefix, len(df) // 3),
            max(min_prefix, (2 * len(df)) // 3),
            len(df) - 5,
        }
    )
    for k in check_points:
        if k <= min_prefix // 2 or k >= len(df):
            continue
        pref = compute_fn(df.iloc[:k].copy()).astype(float)
        # Compare up to k - 2 to allow tiny edge warm-up differences at the cut
        n = min(len(pref), k) - 2
        if n < min_prefix // 2:
            continue
        a = full.iloc[:n].to_numpy(dtype=float)
        b = pref.iloc[:n].to_numpy(dtype=float)
        # NaN positions must match; finite values must be close
        both_nan = np.isnan(a) & np.isnan(b)
        both_fin = np.isfinite(a) & np.isfinite(b)
        if not np.all(both_nan | both_fin):
            bad = int(np.sum(~(both_nan | both_fin)))
            raise AssertionError(
                f"{name}: causal fail at prefix={k}: {bad} NaN-pattern mismatches"
            )
        if both_fin.any() and not np.allclose(a[both_fin], b[both_fin], rtol=rtol, atol=atol):
            diff = np.nanmax(np.abs(a[both_fin] - b[both_fin]))
            raise AssertionError(
                f"{name}: causal fail at prefix={k}: max|Δ|={diff:.3e} (look-ahead?)"
            )


def assert_frame_causal(
    compute_fn: Callable[[pd.DataFrame], pd.DataFrame],
    df: pd.DataFrame,
    columns: list[str],
    *,
    min_prefix: int = 50,
    rtol: float = 1e-9,
    atol: float = 1e-9,
) -> None:
    """Causal check for multi-column indicator frames."""
    for col in columns:

        def _one(frame: pd.DataFrame, c: str = col) -> pd.Series:
            out = compute_fn(frame)
            return out[c]

        assert_series_causal(_one, df, min_prefix=min_prefix, rtol=rtol, atol=atol, name=col)


@dataclass(frozen=True)
class ShiftFinding:
    """A negative ``shift`` / ``shift(periods=-k)`` site in source."""

    where: str
    line: int
    snippet: str
    detail: str


def scan_source_for_negative_shift(source: str, *, where: str = "<module>") -> list[ShiftFinding]:
    """AST-scan source for ``.shift(-n)`` or ``shift(periods=-n)`` (n>0)."""
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return []
    findings: list[ShiftFinding] = []
    lines = source.splitlines()

    def _neg_const(node: ast.AST) -> int | None:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, int | float):
                return int(node.operand.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and node.value < 0:
            return int(-node.value)  # pragma: no cover - parser represents negatives as UnaryOp

        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_shift = (isinstance(func, ast.Attribute) and func.attr == "shift") or (
            isinstance(func, ast.Name) and func.id == "shift"
        )
        if not is_shift:
            continue
        neg: int | None = None
        if node.args:
            neg = _neg_const(node.args[0])
        for kw in node.keywords:
            if kw.arg in {"periods", "periods".lower()} or kw.arg == "periods":
                neg = _neg_const(kw.value) if neg is None else neg
        # Also: shift(-1) via UnaryOp already handled; periods=-1 Constant negative
        if neg is None:
            for kw in node.keywords:
                if kw.arg == "periods":
                    v = kw.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, int | float) and v.value < 0:  # pragma: no cover - parsed negative literals are UnaryOp
                        neg = int(-v.value)  # pragma: no cover - parser represents negatives as UnaryOp
        if node.args and neg is None:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, int | float) and a0.value < 0:  # pragma: no cover - parsed negative literals are UnaryOp
                neg = int(-a0.value)  # pragma: no cover - parser represents negatives as UnaryOp
        if neg is not None and neg > 0:
            line = getattr(node, "lineno", 0)
            snip = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            findings.append(
                ShiftFinding(
                    where=where,
                    line=line,
                    snippet=snip,
                    detail=f"shift(-{neg}) pulls future values (look-ahead)",
                )
            )
    return findings


def scan_callable_for_negative_shift(fn: Callable[..., Any], *, where: str | None = None) -> list[ShiftFinding]:
    """Scan a function/method source for negative shifts."""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return []
    label = where or getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))
    return scan_source_for_negative_shift(src, where=str(label))
