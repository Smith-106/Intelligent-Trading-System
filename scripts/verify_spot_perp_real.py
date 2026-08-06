"""Real-data validation for spot_perp_arb (ISS-20260804-003).

Pipeline over the merged real dataset (data/spot_perp_real/dataset.parquet):

1. Full-window pair backtest with the YAML default params.
2. Signal-participation sensitivity scan: how many entry bars exist at
   relaxed thresholds (documents whether the zero-signal result is a
   threshold artifact or a data-reality absence).
3. Returns-based CPCV: split_cpcv folds, per-fold signal regeneration
   (point-in-time — the strategy uses only current-bar features), per-fold
   OOS pair returns and Sharpe.
4. DSR on the best OOS Sharpe (deflated_sharpe_ratio).
5. Walk-forward evaluation over sequential folds (regenerate signals per
   fold; no fitted parameters — the strategy is parameter-static).
6. Fail-closed GO/NO-GO decision mirroring validation_gate's logic.

Writes data/spot_perp_real/validation_result.json and prints the summary.
Exit code 0 on success (a NO-GO decision is a successful validation run).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantflow.strategy.research.spot_perp_sim import SpotPerpPairSimulator
from quantflow.strategy.validation.cpcv import split_cpcv
from quantflow.strategy.validation.dsr import deflated_sharpe_ratio

DATASET = Path("data/spot_perp_real/dataset.parquet")
OUT = Path("data/spot_perp_real/validation_result.json")
CONFIG_PARAMS = {
    "entry_threshold": 0.001,
    "exit_threshold": 0.0003,
    "oi_lookback": 3,
    "oi_change_threshold": 0.05,
}
CPCV_GROUPS = 6
CPCV_TEST_GROUPS = 1
EMBARGO_PCT = 0.01
WFO_FOLDS = 5


def _fold_returns(df: pd.DataFrame, params: dict) -> pd.Series:
    """Pair per-bar returns for a df slice (0 on the first bar)."""
    res = SpotPerpPairSimulator(params=params, fee_per_leg=0.0005).run(df)
    return res.returns


def _sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    ppy = 365.0 * 24.0  # hourly bars
    return float(r.mean() / r.std() * np.sqrt(ppy))


def _sensitivity_scan(df: pd.DataFrame) -> dict:
    """Entry-bar counts across threshold grid (documents trigger absence)."""
    f = df["funding_rate"].dropna()
    oi = df["open_interest"].dropna()
    oi_chg = oi.pct_change(3).abs()
    rows: dict[str, int] = {}
    for entry_th in [0.001, 0.0005, 0.0003, 0.0002, 0.0001]:
        for oi_th in [0.05, 0.02]:
            funding_mask = (f.abs() >= entry_th).reindex(f.index)
            oi_mask = (oi_chg.reindex(f.index) > oi_th).fillna(False)
            m = funding_mask & oi_mask
            rows[f"entry={entry_th}/oi={oi_th}"] = int(m.sum())
    return {
        "funding_max_abs": float(f.abs().max()),
        "oi_change_max_3bar": float(oi_chg.max()),
        "entry_bars_by_threshold": rows,
    }


def main() -> None:
    df = pd.read_parquet(DATASET)
    report: dict = {
        "dataset": {"n_bars": len(df), "start": str(df.index[0]), "end": str(df.index[-1])}
    }

    # 1. Full-window backtest with config defaults.
    sim = SpotPerpPairSimulator(params=CONFIG_PARAMS, fee_per_leg=0.0005)
    result = sim.run(df)
    report["backtest"] = {
        "params": CONFIG_PARAMS,
        "num_trades": result.num_trades,
        "total_return": result.total_return,
        "sharpe": result.sharpe_ratio,
        "max_drawdown": result.max_drawdown,
        "funding_income": result.funding_income,
        "spread_pnl": result.spread_pnl,
    }
    print(result.summary())

    # 2. Sensitivity scan.
    scan = _sensitivity_scan(df)
    report["sensitivity"] = scan
    print(
        f"\nSensitivity: funding max |f|={scan['funding_max_abs']:.6f}, "
        f"OI 3-bar change max={scan['oi_change_max_3bar']:.4f}"
    )
    for k, v in scan["entry_bars_by_threshold"].items():
        print(f"  {k}: {v} potential entry bars")

    # 3. Returns-based CPCV (per-fold signal regeneration).
    try:
        splits = split_cpcv(len(df), CPCV_GROUPS, CPCV_TEST_GROUPS, EMBARGO_PCT)
    except ValueError as exc:  # pragma: no cover - tiny windows only
        print(f"CPCV skipped: {exc}")
        splits = []
    oos_sharpes: list[float] = []
    fold_returns: list[float] = []
    for _train_idx, test_idx in splits:
        test_frame = df.iloc[test_idx]
        r = _fold_returns(test_frame, CONFIG_PARAMS)
        oos_sharpes.append(_sharpe(r))
        fold_returns.append(float(r.sum()))
    report["cpcv"] = {
        "n_paths": len(oos_sharpes),
        "oos_sharpes": oos_sharpes,
        "oos_returns": fold_returns,
    }
    finite = [s for s in oos_sharpes if np.isfinite(s) and s != 0.0]
    print(
        f"\nCPCV: {len(oos_sharpes)} OOS paths, Sharpe distribution: {np.round(oos_sharpes, 3).tolist()}"
    )

    # 4. DSR on best OOS Sharpe.
    best_oos = float(np.nanmax(oos_sharpes)) if oos_sharpes else 0.0
    dsr = deflated_sharpe_ratio(
        observed_sharpe=best_oos,
        n_trials=20,
        sample_length=len(df),
        annualize_factor=365 * 24,
    )
    report["dsr"] = {"best_oos_sharpe": best_oos, **dsr}
    print(
        f"DSR: best OOS Sharpe={best_oos:.4f} -> dsr={dsr.get('dsr', 0.0):.4f} passed={dsr.get('passed')}"
    )

    # 5. Walk-forward evaluation (sequential folds, per-fold signals).
    n = len(df)
    fold_size = n // WFO_FOLDS
    wfo_folds: list[dict] = []
    for i in range(WFO_FOLDS):
        test_slice = df.iloc[i * fold_size : min((i + 1) * fold_size, n)]
        r = _fold_returns(test_slice, CONFIG_PARAMS)
        wfo_folds.append(
            {
                "fold": i,
                "start": str(test_slice.index[0]),
                "end": str(test_slice.index[-1]),
                "test_sharpe": _sharpe(r),
                "test_return": float(r.sum()),
                "n_trades": int(
                    SpotPerpPairSimulator(params=CONFIG_PARAMS, fee_per_leg=0.0005)
                    .run(test_slice)
                    .num_trades
                ),
            }
        )
    mean_test_sharpe = float(np.mean([f_["test_sharpe"] for f_ in wfo_folds]))
    report["wfo"] = {"folds": wfo_folds, "mean_test_sharpe": mean_test_sharpe}

    # 6. Fail-closed gate.
    checks: dict[str, dict] = {}
    decision = "NO-GO"
    reason = ""

    if not finite:
        reason = "0 OOS paths with non-zero Sharpe (no signals in window)"
        checks["cpcv"] = {"passed": False, "reason": reason}
    elif not dsr.get("passed", False):
        reason = f"DSR={dsr.get('dsr', 0.0):.4f} < 0.95"
        checks["cpcv"] = {"passed": True, "reason": "OOS Sharpe paths exist"}
        checks["dsr"] = {"passed": False, "reason": reason}
    elif mean_test_sharpe <= 0:
        reason = f"WFO mean test Sharpe={mean_test_sharpe:.4f} <= 0"
        checks["cpcv"] = {"passed": True}
        checks["dsr"] = {"passed": True}
        checks["wfo"] = {"passed": False, "reason": reason}
    else:
        decision = "GO"
        reason = "All validation checks passed"
        checks = {"cpcv": {"passed": True}, "dsr": {"passed": True}, "wfo": {"passed": True}}

    report["gate"] = {"decision": decision, "reason": reason, "checks": checks}
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n=== VALIDATION GATE: {decision} ===")
    print(f"Reason: {reason}")
    print(f"Report: {OUT}")


if __name__ == "__main__":
    main()
