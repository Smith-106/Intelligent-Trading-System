#!/usr/bin/env python3
"""Pre-flight checks for daily Baseline-0 paper sessions.

Contract: docs/research/Candidate-Baseline-0.md
Checklist: docs/research/baseline0-paper-run-checklist.md

Exit 0 = OK to start ``quantflow run --mode paper ...`` with the overlay.
Exit 1 = fix reported issues first.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OVERLAY = REPO_ROOT / "quantflow" / "config" / "paper_baseline0_overlay.yaml"
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
MAX_BAR_AGE_HOURS = 48.0
MIN_BARS = 500
# P0 T003: composite data-quality score floor for paper day-session.
MIN_DATA_QUALITY_SCORE = 0.7
# T016 defaults (also in risk.paper_readiness YAML).
MIN_PAPER_DAYS = 7.0
MIN_PAPER_FILLS = 20


def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _check_paper_readiness_config() -> list[str]:
    """Surface T016 thresholds (informational + config presence)."""
    notes: list[str] = []
    try:
        from quantflow.common.config import load_config

        cfg = load_config()
        pr = cfg.risk.paper_readiness
        notes.append(
            f"paper_readiness enabled={pr.enabled} "
            f"min_days={pr.min_paper_days} min_fills={pr.min_fills} "
            f"(promote_to_live fail-closed when short)"
        )
        if not pr.enabled:
            notes.append("WARN: paper_readiness.enabled=false — live promote sample gate OFF")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"paper_readiness config unreadable: {exc}")
    return notes


def main() -> int:
    print("Baseline-0 paper preflight")
    print(f"  repo: {REPO_ROOT}")
    failures = 0

    # --- version ---
    try:
        import quantflow

        ver = getattr(quantflow, "__version__", "?")
        _ok(f"quantflow {ver}")
        if not str(ver).startswith("0.5") and not str(ver).startswith("0.6"):
            _warn(f"expected 0.5.x for Baseline-0 era; got {ver}")
    except Exception as e:
        _fail(f"import quantflow: {e}")
        failures += 1

    # --- overlay ---
    if not OVERLAY.is_file():
        _fail(f"missing overlay: {OVERLAY}")
        failures += 1
    else:
        try:
            from quantflow.common.config import load_config

            cfg = load_config(OVERLAY)
            po = cfg.risk.portfolio_optimization
            checks = [
                (cfg.execution.mode == "paper", f"execution.mode={cfg.execution.mode!r}"),
                (
                    abs(float(cfg.execution.taker_fee) - 0.001) < 1e-12,
                    f"taker_fee={cfg.execution.taker_fee}",
                ),
                (
                    abs(float(cfg.execution.slippage) - 0.001) < 1e-12,
                    f"slippage={cfg.execution.slippage}",
                ),
                (po.enabled is True, f"portfolio_optimization.enabled={po.enabled}"),
                (po.method == "risk_parity", f"method={po.method!r}"),
                (po.level == "symbol", f"level={po.level!r}"),
                (
                    int(po.rebalance_every_n_bars) == 48,
                    f"rebalance_every_n_bars={po.rebalance_every_n_bars}",
                ),
            ]
            for good, label in checks:
                if good:
                    _ok(f"overlay {label}")
                else:
                    _fail(f"overlay contract mismatch: {label}")
                    failures += 1
        except Exception as e:
            _fail(f"load overlay: {e}")
            failures += 1

    # --- default.yaml must stay RP-off ---
    try:
        from quantflow.common.config import load_config

        default_cfg = load_config(REPO_ROOT / "quantflow" / "config" / "default.yaml")
        if default_cfg.risk.portfolio_optimization.enabled:
            _fail("default.yaml portfolio_optimization.enabled=true (should stay false)")
            failures += 1
        else:
            _ok("default.yaml portfolio_optimization.enabled=false (good)")
    except Exception as e:
        _warn(f"could not read default.yaml: {e}")

    # --- market data + quality score (P0 T003) ---
    try:
        from quantflow.data.store import DataStore

        store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
        now_ms = int(time.time() * 1000)
        quality_scores: list[float] = []
        for sym in SYMBOLS:
            df = store.query(sym, timeframe="1h")
            n = len(df)
            if n < MIN_BARS:
                _fail(f"{sym} 1h bars={n} (< {MIN_BARS})")
                failures += 1
                quality_scores.append(0.0)
                continue
            ts = int(df["timestamp"].astype("int64").max())
            age_h = (now_ms - ts) / 3_600_000.0
            if age_h > MAX_BAR_AGE_HOURS:
                _warn(
                    f"{sym} 1h last bar age={age_h:.1f}h (> {MAX_BAR_AGE_HOURS}h) — "
                    "consider quantflow download"
                )
            score = _history_quality_score(df, now_ms=now_ms)
            quality_scores.append(score)
            label = f"{sym} 1h bars={n} age={age_h:.1f}h quality={score:.2f}"
            if score < MIN_DATA_QUALITY_SCORE:
                _fail(f"{label} (< {MIN_DATA_QUALITY_SCORE})")
                failures += 1
            else:
                _ok(label)
        if quality_scores:
            avg_q = sum(quality_scores) / len(quality_scores)
            if avg_q < MIN_DATA_QUALITY_SCORE:
                _fail(
                    f"portfolio data quality avg={avg_q:.2f} "
                    f"(< {MIN_DATA_QUALITY_SCORE})"
                )
                failures += 1
            else:
                _ok(f"portfolio data quality avg={avg_q:.2f}")
        store.close()
    except Exception as e:
        _fail(f"data store: {e}")
        failures += 1

    # --- T016 paper readiness floors (informational; promote path is fail-closed) ---
    print()
    print("Paper readiness (T016 — paper→live sample floors):")
    for note in _check_paper_readiness_config():
        if note.startswith("WARN"):
            _warn(note)
        elif "unreadable" in note:
            _warn(note)
        else:
            _ok(note)
    _ok(
        f"promote_to_live requires paper_evidence with "
        f"≥{MIN_PAPER_DAYS}d and ≥{MIN_PAPER_FILLS} fills (defaults)"
    )

    # --- run command reminder ---
    print()
    print("Start command (path A — daily paper, no nested gate):")
    print(
        "  quantflow run --mode paper --strategy trend_following "
        "--symbols BTC/USDT,ETH/USDT,SOL/USDT --timeframe 1h --interval 60 "
        "--capital 100000 --config quantflow/config/paper_baseline0_overlay.yaml"
    )
    print("Research parity (path B — nested gate, matches gate.json):")
    print("  python scripts/run_baseline0.py")
    print()
    if failures:
        print(f"PREFLIGHT FAILED ({failures} error(s))")
        return 1
    print("PREFLIGHT OK — safe to start paper session")
    return 0


def _history_quality_score(df, *, now_ms: int) -> float:
    """Composite 0–1 score: freshness / continuity / anomaly (static history).

    Mirrors DataQualityScore weights without requiring live Redis state.
    """
    import pandas as pd

    if df is None or len(df) == 0:
        return 0.0

    ts = pd.to_numeric(df["timestamp"], errors="coerce").dropna().astype("int64")
    if ts.empty:
        return 0.0

    # Freshness: full score if last bar within 24h; linear decay to 0 at 96h.
    age_h = max(0.0, (now_ms - int(ts.max())) / 3_600_000.0)
    if age_h <= 24.0:
        freshness = 1.0
    elif age_h >= 96.0:
        freshness = 0.0
    else:
        freshness = max(0.0, 1.0 - (age_h - 24.0) / 72.0)

    # Continuity: fraction of consecutive 1h gaps that are ~1 bar (allow 1–2h).
    ordered = ts.sort_values().to_numpy()
    if len(ordered) < 2:
        continuity = 0.5
    else:
        gaps = (ordered[1:] - ordered[:-1]) / 3_600_000.0
        ok = ((gaps >= 0.5) & (gaps <= 2.5)).sum()
        continuity = float(ok) / float(len(gaps))

    # Anomaly: penalize extreme close-to-close jumps (>20%).
    if "close" in df.columns and len(df) >= 3:
        close = pd.to_numeric(df["close"], errors="coerce").dropna()
        rets = close.pct_change().dropna().abs()
        if rets.empty:
            anomaly = 1.0
        else:
            spike_rate = float((rets > 0.20).mean())
            anomaly = max(0.0, 1.0 - spike_rate * 5.0)
    else:
        anomaly = 0.8

    # Weights match DataQualityScore: 40% / 30% / 30%.
    return freshness * 0.4 + continuity * 0.3 + anomaly * 0.3


if __name__ == "__main__":
    raise SystemExit(main())
