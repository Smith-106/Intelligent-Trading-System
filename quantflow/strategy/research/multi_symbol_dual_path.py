"""Multi-symbol dual-path research report (IMP-04).

OKX multi-symbol only (not multi-exchange). Runs Path A (overlay) and Path B
(TPSL) per symbol, side-by-side. Never emits combined_score.
promotion_eligible always false. Honest execution_path=vectorized + fingerprints.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.research.benchmark_excess import (
    buy_hold_equity_from_close,
    equity_stats,
    excess_vs_benchmark,
    gate_beats_benchmark,
)
from quantflow.strategy.research.contract_pin import fingerprint_ohlcv
from quantflow.strategy.research.dual_path_profiles import path_a_profile, path_b_profile
from quantflow.strategy.research.dual_path_report import (
    RESEARCH_EXECUTION_PATH,
    assert_no_combined_score,
    build_dual_path_report,
    from_overlay_eval,
    from_tpsl_eval,
)
from quantflow.strategy.research.tpsl import (
    TPSLConfig,
    dual_ma_entries,
    simulate_long_flat_tpsl,
)

CONTRACT_ID = "MULTI-SYMBOL-DUAL-PATH-20260811"


def _simulate_path_a(close: pd.Series, profile: dict[str, Any]) -> dict[str, Any]:
    """Path A continuous overlay via beta-overlay simulator."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.run_btc_beta_overlay_eval import _simulate_beta_overlay

    eq, meta = _simulate_beta_overlay(
        close,
        overlay_weight=float(profile["overlay_weight"]),
        fee=float(profile["fee"]),
        slip=float(profile["slip"]),
        fast=int(profile["fast"]),
        slow=int(profile["slow"]),
        mode=str(profile["mode"]),
    )
    btc_eq = buy_hold_equity_from_close(close)
    vs = excess_vs_benchmark(eq, btc_eq, label="PATH_A", benchmark_label="HODL")
    gate = gate_beats_benchmark(vs)
    return {
        "primary_overlay_reduce_off": {
            "meta": meta,
            "return_pct": vs.strategy_return_pct,
            "excess_return_pct": vs.excess_return_pct,
            "max_dd_pct": vs.strategy_max_dd_pct,
            "gate": gate.get("decision"),
            "beats_btc": vs.beats_benchmark,
        },
        "hodl": equity_stats(btc_eq),
    }


def _simulate_path_b(df: pd.DataFrame, profile: dict[str, Any]) -> dict[str, Any]:
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    entries, sig_on = dual_ma_entries(close, int(profile["fast"]), int(profile["slow"]))
    cfg = TPSLConfig(
        stop_loss_pct=float(profile["stop_loss_pct"]),
        take_profit_pct=float(profile["take_profit_pct"]),
        min_rr=float(profile["min_rr"]),
        max_holding_bars=int(profile.get("max_holding_bars") or 0),
        fee=float(profile["fee"]),
        slip=float(profile["slip"]),
    )
    eq, _trades, stats, meta = simulate_long_flat_tpsl(
        close, entries, high=high, low=low, signal_on=sig_on, cfg=cfg
    )
    hodl_eq = buy_hold_equity_from_close(close)
    vs = excess_vs_benchmark(eq, hodl_eq, label="PATH_B", benchmark_label="HODL")
    gate = gate_beats_benchmark(vs)
    st = equity_stats(eq)
    return {
        "tpsl_default": {
            "config": meta.get("config", {}),
            "return_pct": vs.strategy_return_pct,
            "excess_return_pct": vs.excess_return_pct,
            "max_dd_pct": vs.strategy_max_dd_pct,
            "sharpe": st.get("sharpe"),
            "gate": gate.get("decision"),
            "beats_btc": vs.beats_benchmark,
            "trade_stats": stats.to_dict(),
            "n_trades": stats.n_trades,
        }
    }


def equal_book_weights(symbols: list[str]) -> dict[str, float]:
    """Equal capital weights across symbols (sum=1)."""
    n = len(symbols)
    if n == 0:
        return {}
    w = 1.0 / n
    return {s: w for s in symbols}


def run_symbol_dual_path(
    df: pd.DataFrame,
    *,
    symbol: str,
    path_a: dict[str, Any] | None = None,
    path_b: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate Path A/B for one symbol frame."""
    if df is None or df.empty or "close" not in df.columns:
        raise ValueError(f"{symbol}: df with close required (fail-closed)")
    pa = path_a or path_a_profile()
    pb = path_b or path_b_profile()
    close = df["close"].astype(float)
    overlay = _simulate_path_a(close, pa)
    tpsl = _simulate_path_b(df, pb)
    fp = {"aggregate": fingerprint_ohlcv(df), "symbol": symbol, "bars": len(df)}
    return {
        "symbol": symbol,
        "bars": len(df),
        "data_fingerprint": fp,
        "path_a": from_overlay_eval(overlay, profile=pa),
        "path_b": from_tpsl_eval(tpsl, profile=pb),
        "hodl": overlay.get("hodl"),
        "promotion_eligible": False,
    }


def build_multi_symbol_dual_path_report(
    frames: dict[str, pd.DataFrame],
    *,
    path_a: dict[str, Any] | None = None,
    path_b: dict[str, Any] | None = None,
    book_weights: dict[str, float] | None = None,
    run_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build multi-symbol dual-path envelope (no combined_score).

    ``frames`` maps symbol → OHLCV DataFrame (OKX style keys e.g. BTC/USDT).
    """
    if not frames or len(frames) < 2:
        raise ValueError("need >=2 symbols for multi-symbol dual-path (fail-closed)")

    symbols = sorted(frames.keys())
    weights = book_weights or equal_book_weights(symbols)
    # normalize weights
    total_w = sum(float(weights.get(s, 0.0)) for s in symbols) or 1.0
    weights = {s: float(weights.get(s, 0.0)) / total_w for s in symbols}

    per_symbol: dict[str, Any] = {}
    fingerprints: dict[str, Any] = {}
    for sym in symbols:
        block = run_symbol_dual_path(
            frames[sym], symbol=sym, path_a=path_a, path_b=path_b
        )
        per_symbol[sym] = block
        fingerprints[sym] = block["data_fingerprint"]

    # Book-level narrative: weighted excess (display only — not a promotion score)
    wa = 0.0
    wb = 0.0
    for sym, block in per_symbol.items():
        w = weights[sym]
        am = (block.get("path_a") or {}).get("metrics") or {}
        bm = (block.get("path_b") or {}).get("metrics") or {}
        if am.get("excess_return_pct") is not None:
            wa += w * float(am["excess_return_pct"])
        if bm.get("excess_return_pct") is not None:
            wb += w * float(bm["excess_return_pct"])

    # Dual-path envelope for primary symbol (first) + multi attachment
    primary = symbols[0]
    dual = build_dual_path_report(
        path_a=per_symbol[primary]["path_a"],
        path_b=per_symbol[primary]["path_b"],
        run_meta={
            "contract": CONTRACT_ID,
            "symbols": symbols,
            "primary_symbol": primary,
            **(run_meta or {}),
        },
        attachments={
            "multi_symbol": {
                "symbols": symbols,
                "book_weights": weights,
                "per_symbol": {
                    s: {
                        "bars": per_symbol[s]["bars"],
                        "path_a_metrics": (per_symbol[s]["path_a"].get("metrics") or {}),
                        "path_b_metrics": (per_symbol[s]["path_b"].get("metrics") or {}),
                        "data_fingerprint": per_symbol[s]["data_fingerprint"],
                    }
                    for s in symbols
                },
                "book_display": {
                    "weighted_path_a_excess_pct": wa,
                    "weighted_path_b_excess_pct": wb,
                    "note": (
                        "display-only weighted excess; NOT combined_score; "
                        "NOT promotion decision"
                    ),
                },
            }
        },
        data_fingerprint={
            "symbols": fingerprints,
            "aggregate": "|".join(
                f"{s}:{fingerprints[s].get('aggregate')}" for s in symbols
            ),
        },
        execution_path=RESEARCH_EXECUTION_PATH,
        complete=True,
    )
    out = dual.to_dict()
    out["contract_multi"] = CONTRACT_ID
    out["symbols"] = symbols
    out["book"] = {
        "weights": weights,
        "allocation_mode": "equal" if book_weights is None else "custom",
        "portfolio_traceable": True,
    }
    out["per_symbol"] = {
        s: {
            "bars": per_symbol[s]["bars"],
            "path_a": per_symbol[s]["path_a"],
            "path_b": per_symbol[s]["path_b"],
            "data_fingerprint": per_symbol[s]["data_fingerprint"],
            "promotion_eligible": False,
        }
        for s in symbols
    }
    out["promotion_eligible"] = False
    assert_no_combined_score(out)
    return out


def synth_ohlcv(n: int = 800, *, seed: int = 1, drift: float = 0.0002) -> pd.DataFrame:
    """Synthetic OHLCV for unit tests."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    open_ = close * (1 + rng.normal(0, 0.001, n))
    ts0 = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    stamps = [ts0 + i * 3_600_000 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1, 10, n),
        }
    )
