"""Path B TPSL validation report with honest n_trials (research, no promote)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantflow.strategy.research.n_trials_budget import (
    TrialsBreakdown,
    account_n_trials,
    assert_honest_n_trials,
    grid_size,
)
from quantflow.strategy.research.tpsl_gate_adapter import (
    barrier_param_space,
    make_dual_ma_tpsl_signal_fn,
)
from quantflow.strategy.validation.gate import validation_gate


def build_tpsl_validation_report(
    data: pd.DataFrame,
    *,
    fast: int = 96,
    slow: int = 400,
    param_space: dict[str, tuple[Any, ...]] | None = None,
    optimize_trials: int = 5,
    cpcv_groups: int = 4,
    cpcv_test_groups: int = 1,
    wfo_windows: int = 2,
    fee: float = 0.001,
    claimed_n_trials: int | None = None,
    run_gate: bool = True,
) -> dict[str, Any]:
    """Run (optional) validation_gate on dual-MA+TPSL adapter with honest N.

    Always returns promotion_eligible=False. Labels PBO as CPCV-embedded.
    """
    if data is None or data.empty or "close" not in data.columns:
        raise ValueError("data with close column required (fail-closed)")

    space = param_space or barrier_param_space(
        stop_loss_pcts=(0.04,),
        min_rrs=(2.5,),
        max_holds=(0,),
    )
    n_grid = grid_size(space)
    # CPCV path count approx C(groups, test_groups) — report as upper bound note
    from math import comb

    cpcv_paths = comb(cpcv_groups, cpcv_test_groups) if cpcv_groups >= cpcv_test_groups else 0
    breakdown = TrialsBreakdown(
        barrier_grid=n_grid,
        optimize_trials=int(optimize_trials),
        cpcv_paths=int(cpcv_paths),
        wfo_windows=int(wfo_windows),
        manual_sweeps=0,
        other=0,
    )
    acc = account_n_trials(breakdown)
    if claimed_n_trials is not None:
        acc = assert_honest_n_trials(claimed_n_trials, breakdown)

    close = data["close"]
    signal_fn = make_dual_ma_tpsl_signal_fn(fast=fast, slow=slow)
    # baseline fixed entries/exits at defaults
    entries, exits = signal_fn(data)

    report: dict[str, Any] = {
        "promotion_eligible": False,
        "execution_models": {
            "vectorized_adapter": True,
            "tpsl_simulator": False,
            "note": "vectorized close-path exits ≠ high/low TPSL simulator",
        },
        "pbo_source": "CPCV-embedded",
        "n_trials_accounted": acc.n_trials_accounted,
        "n_trials_breakdown": acc.breakdown,
        "underreported": acc.underreported,
        "notes": list(acc.notes),
        "param_space": {k: list(v) for k, v in space.items()},
        "validation": None,
        "decision": None,
    }

    if acc.underreported:
        report["decision"] = "NO-GO"
        report["reason"] = "underreported n_trials — refuse GO"
        return report

    if not run_gate:
        report["decision"] = None
        report["notes"].append("gate skipped (run_gate=False)")
        return report

    # Optuna bayesian expects continuous (low, high). Discrete barrier axes are
    # enumerated via optimize_method=grid. Single-point spaces skip in-gate
    # optimization and evaluate fixed dual-MA+TPSL entries/exits only.
    multi_point = any(len(tuple(v)) > 1 for v in space.values())
    gate_kwargs: dict[str, Any] = {
        "n_trials": acc.n_trials_accounted,
        "cpcv_groups": cpcv_groups,
        "cpcv_test_groups": cpcv_test_groups,
        "wfo_windows": wfo_windows,
        "fee": fee,
    }
    if multi_point:
        gate_kwargs.update(
            {
                "signal_fn": signal_fn,
                "param_space": space,
                "data": data,
                "optimize_trials": optimize_trials,
                "optimize_method": "grid",
            }
        )
        report["notes"].append("in-gate optimize_method=grid for discrete barrier space")
    else:
        report["notes"].append("fixed barrier config — no in-gate param optimize")

    gate_out = validation_gate(close, entries, exits, **gate_kwargs)
    report["validation"] = gate_out
    report["decision"] = gate_out.get("decision")
    # Never allow promote from this research envelope
    report["promotion_eligible"] = False
    # unreachable: acc.underreported is False here (early return above) and no
    # code path can flip report["underreported"] afterwards.
    if report.get("underreported"):  # pragma: no cover - defensive guard, impossible after line 87 early return
        report["decision"] = "NO-GO"
    return report
