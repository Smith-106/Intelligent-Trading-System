"""QuantFlow strategy research — backtesting, dual-path OS, and optimization.

Public surface prefers dual-path / Path B helpers used by scripts and tests.
Heavy modules remain import-lazy via explicit submodule paths when needed.
"""

from __future__ import annotations

from quantflow.strategy.research.backtest import BacktestEngine, BacktestResult
from quantflow.strategy.research.btc_overlay_profiles import (
    PRIMARY,
    primary_eval_kwargs,
)
from quantflow.strategy.research.btc_overlay_profiles import (
    PROFILES as BTC_OVERLAY_PROFILES,
)
from quantflow.strategy.research.btc_overlay_profiles import (
    get_profile as get_btc_overlay_profile,
)
from quantflow.strategy.research.dual_path_profiles import (
    assert_aligned_with_primary,
    forbid_combined_score_enabled,
    load_dual_path_profiles,
    path_a_profile,
    path_b_profile,
)
from quantflow.strategy.research.dual_path_report import (
    RESEARCH_EXECUTION_PATH,
    DualPathResearchReport,
    assert_no_combined_score,
    build_dual_path_report,
    dual_path_report_to_promotion_view,
    from_overlay_eval,
    from_tpsl_eval,
)
from quantflow.strategy.research.dual_path_report import (
    to_json as dual_path_to_json,
)
from quantflow.strategy.research.dual_path_report import (
    to_markdown as dual_path_to_markdown,
)
from quantflow.strategy.research.optimizer import StrategyOptimizer
from quantflow.strategy.research.path_b_oos import (
    build_path_b_cost_attachment,
    run_path_b_multi_window_oos,
)

__all__ = [
    "BTC_OVERLAY_PROFILES",
    "PRIMARY",
    "RESEARCH_EXECUTION_PATH",
    "BacktestEngine",
    "BacktestResult",
    "DualPathResearchReport",
    "StrategyOptimizer",
    "assert_aligned_with_primary",
    "assert_no_combined_score",
    "build_dual_path_report",
    "build_path_b_cost_attachment",
    "dual_path_report_to_promotion_view",
    "dual_path_to_json",
    "dual_path_to_markdown",
    "forbid_combined_score_enabled",
    "from_overlay_eval",
    "from_tpsl_eval",
    "get_btc_overlay_profile",
    "load_dual_path_profiles",
    "path_a_profile",
    "path_b_profile",
    "primary_eval_kwargs",
    "run_path_b_multi_window_oos",
]
