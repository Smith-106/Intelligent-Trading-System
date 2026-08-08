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


def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


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

    # --- market data ---
    try:
        from quantflow.data.store import DataStore

        store = DataStore(str(REPO_ROOT / "data" / "parquet"), ":memory:")
        now_ms = int(time.time() * 1000)
        for sym in SYMBOLS:
            df = store.query(sym, timeframe="1h")
            n = len(df)
            if n < MIN_BARS:
                _fail(f"{sym} 1h bars={n} (< {MIN_BARS})")
                failures += 1
                continue
            ts = int(df["timestamp"].astype("int64").max())
            age_h = (now_ms - ts) / 3_600_000.0
            if age_h > MAX_BAR_AGE_HOURS:
                _warn(
                    f"{sym} 1h last bar age={age_h:.1f}h (> {MAX_BAR_AGE_HOURS}h) — "
                    "consider quantflow download"
                )
            _ok(f"{sym} 1h bars={n} age={age_h:.1f}h")
        store.close()
    except Exception as e:
        _fail(f"data store: {e}")
        failures += 1

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


if __name__ == "__main__":
    raise SystemExit(main())
