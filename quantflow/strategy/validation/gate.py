"""GO/NO-GO Decision Gate — unified validation pipeline.

Runs the full validation sequence:
1. CPCV multi-path validation (PBO < 0.5)
2. DSR statistical correction (DSR > 0.95)
3. Walk-Forward OOS efficiency (> 50%)
All must pass for GO decision.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pandas as pd

from quantflow.strategy.validation.cpcv import cpcv_backtest
from quantflow.strategy.validation.dsr import deflated_sharpe_ratio
from quantflow.strategy.validation.wfo import walk_forward_optimization

logger = logging.getLogger(__name__)
SignalFunction = Callable[..., tuple[pd.Series, pd.Series]]


def validation_gate(
    close: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    n_trials: int = 100,
    cpcv_groups: int = 8,
    cpcv_test_groups: int = 2,
    wfo_windows: int = 5,
    initial_capital: float = 10000.0,
    fee: float = 0.001,
    signal_fn: SignalFunction | None = None,
    param_space: dict[str, tuple[Any, ...]] | None = None,
    data: pd.DataFrame | None = None,
    optimize_trials: int = 50,
    optimize_method: str = "bayesian",
    optimize_objective: str = "sharpe",
    win_rate_threshold: float | None = None,
) -> dict[str, Any]:
    """Run the full GO/NO-GO validation pipeline.

    Returns dict with all validation results and final decision.
    """
    results: dict[str, Any] = {
        "decision": "NO-GO",
        "checks": {},
    }

    # Step 1: CPCV
    logger.info("=== Step 1: CPCV Validation ===")
    cpcv_result = cpcv_backtest(
        close,
        entries,
        exits,
        n_groups=cpcv_groups,
        n_test_groups=cpcv_test_groups,
        initial_capital=initial_capital,
        fee=fee,
        signal_fn=signal_fn,
        param_space=param_space,
        data=data,
        n_trials=optimize_trials,
        method=optimize_method,
        objective=optimize_objective,
    )
    results["checks"]["cpcv"] = cpcv_result
    if not cpcv_result["passed"]:
        results["decision"] = "NO-GO"
        results["reason"] = str(
            cpcv_result.get("reason") or f"CPCV PBO={cpcv_result['pbo']:.3f} >= 0.5"
        )
        return results

    # Step 2: DSR
    logger.info("=== Step 2: DSR Validation ===")
    best_oos_sharpe = max(p["oos_sharpe"] for p in cpcv_result["path_results"])
    dsr_result = deflated_sharpe_ratio(
        observed_sharpe=best_oos_sharpe,
        n_trials=n_trials,
        sample_length=len(close),
    )
    results["checks"]["dsr"] = dsr_result
    if not dsr_result["passed"]:
        results["decision"] = "NO-GO"
        results["reason"] = f"DSR={dsr_result['dsr']:.4f} < 0.95"
        return results

    # Optional: win_rate threshold check
    if win_rate_threshold is not None:
        avg_wr = sum(p.get("oos_win_rate", 0.5) for p in cpcv_result["path_results"]) / len(
            cpcv_result["path_results"]
        )
        if avg_wr < win_rate_threshold:
            results["decision"] = "NO-GO"
            results["reason"] = f"CPCV avg win_rate={avg_wr:.3f} < {win_rate_threshold}"
            results["checks"]["win_rate"] = {
                "avg_win_rate": avg_wr,
                "threshold": win_rate_threshold,
                "passed": False,
            }
            return results
        results["checks"]["win_rate"] = {
            "avg_win_rate": avg_wr,
            "threshold": win_rate_threshold,
            "passed": True,
        }

    # Step 3: WFO
    logger.info("=== Step 3: Walk-Forward Validation ===")
    wfo_rolling = walk_forward_optimization(
        close,
        entries,
        exits,
        n_windows=wfo_windows,
        mode="rolling",
        initial_capital=initial_capital,
        fee=fee,
        signal_fn=signal_fn,
        param_space=param_space,
        data=data,
        n_trials=optimize_trials,
        method=optimize_method,
        objective=optimize_objective,
    )
    results["checks"]["wfo_rolling"] = wfo_rolling

    wfo_anchored = walk_forward_optimization(
        close,
        entries,
        exits,
        n_windows=wfo_windows,
        mode="anchored",
        initial_capital=initial_capital,
        fee=fee,
        signal_fn=signal_fn,
        param_space=param_space,
        data=data,
        n_trials=optimize_trials,
        method=optimize_method,
        objective=optimize_objective,
    )
    results["checks"]["wfo_anchored"] = wfo_anchored

    # Both WFO modes must pass
    if not wfo_rolling["passed"] or not wfo_anchored["passed"]:
        results["decision"] = "NO-GO"
        results["reason"] = (
            f"WFO rolling eff={wfo_rolling['oos_efficiency']:.3f}, "
            f"anchored eff={wfo_anchored['oos_efficiency']:.3f}"
        )
        return results

    # All checks passed
    results["decision"] = "GO"
    results["reason"] = "All validation checks passed"
    logger.info("=== VALIDATION GATE: GO ===")
    return results
