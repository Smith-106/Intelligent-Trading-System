"""s4 strategy-factory pipeline end-to-end verification (T-s4-05).

Exercises the full s4 loop with synthetic data (CI-safe, no external deps):

  1. Dynamic budget: RiskEngine with dynamic_budget enabled — high volatility
     shrinks a strategy's budget (fail-closed); disabled config is a no-op.
  2. Auto research loop: AutoResearchLoop runs one train → validate →
     register/reject iteration with the real ModelRegistry (synthetic random
     data cannot pass the gate, so the expected outcome is a fail-closed
     rejected entry + JSONL decision log).
  3. AI factor strategy: empty registry degrades to momentum (no signals
     lost); a seeded paper model gates momentum entries.
  4. Spot-perp prototype: symmetric signals on synthetic funding/OI.

Exit code 0 on success — usable as a CI gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantflow.common.config import DynamicBudgetConfig, RiskConfig
from quantflow.signal.risk_engine import RiskEngine
from quantflow.strategy.auto_loop import AutoLoopConfigModel, AutoResearchLoop
from quantflow.strategy.model_registry import ModelRegistry
from quantflow.strategy.templates.ai_factor_strategy import AIFactorStrategy
from quantflow.strategy.templates.spot_perp_arb import SpotPerpArbStrategy

WORK = Path("data/s4_verify")
WORK.mkdir(parents=True, exist_ok=True)


def _returns(n: int, seed: int, vol: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, vol, n)


def _df(n: int = 300) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    close = pd.Series(100.0 + np.linspace(0, 5, n), index=idx)
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1000.0},
        index=idx,
    )


def step1_dynamic_budget() -> None:
    """Dynamic budget scales down under high volatility; disabled = no-op."""
    budgets = {"s1": 0.5}
    # Disabled → static budget unchanged even with wild returns.
    static = RiskEngine(RiskConfig(position_limit_pct=1.0), strategy_risk_budgets=budgets)
    for r in _returns(200, 1, 0.05):
        static.add_return(float(r))
    assert static._scale_budget_pct("s1", 0.5) == 0.5, "disabled dynamic budget must be static"

    cfg = DynamicBudgetConfig(enabled=True, target_vol_pct=0.15, min_scale=0.5, max_scale=1.5)
    dyn = RiskEngine(RiskConfig(position_limit_pct=1.0, dynamic_budget=cfg), strategy_risk_budgets=budgets)
    for r in _returns(200, 1, 0.05):
        dyn.add_return(float(r))
    scaled = dyn._scale_budget_pct("s1", 0.5)
    assert scaled < 0.5, f"high vol must shrink budget, got {scaled}"

    # Short history → fail-safe fallback to static.
    dyn2 = RiskEngine(RiskConfig(position_limit_pct=1.0, dynamic_budget=cfg), strategy_risk_budgets=budgets)
    for r in _returns(10, 2, 0.05):
        dyn2.add_return(float(r))
    assert dyn2._scale_budget_pct("s1", 0.5) == 0.5
    print("step1 dynamic_budget: PASS")


def step2_auto_loop() -> None:
    """Auto loop: synthetic data → NO-GO → rejected entry + JSONL log."""
    registry = ModelRegistry(str(WORK / "models"))
    log = WORK / "decisions.jsonl"
    if log.exists():
        log.unlink()
    cfg = AutoLoopConfigModel(
        log_path=str(log),
        training_kwargs={"test_size": 0.3, "random_state": 1},
        validation_kwargs={"n_trials": 5, "cpcv_groups": 3, "cpcv_test_groups": 1, "wfo_windows": 2},
    )
    loop = AutoResearchLoop(registry=registry, config=cfg)
    idx = pd.date_range("2026-01-01", periods=300, freq="h")
    rng = pd.DataFrame({"rsi": pd.Series(50.0, index=idx, dtype=float)}, index=idx)
    close = pd.Series(100.0, index=idx, dtype=float)

    from sklearn.ensemble import RandomForestClassifier

    decision = loop.run_once(rng, close, RandomForestClassifier, n_estimators=5)
    assert decision.decision == "NO-GO", "synthetic data must fail the gate (fail-closed)"
    entries = registry.list_models()
    assert any(e["model_id"] == decision.model_id and e["status"] == "rejected" for e in entries)
    assert log.exists() and len(log.read_text(encoding="utf-8").strip().splitlines()) == 1
    print("step2 auto_loop: PASS (NO-GO → rejected + logged)")


def step3_ai_factor_strategy() -> None:
    """Empty registry → momentum degradation; seeded model gates entries."""
    empty_dir = WORK / "empty_registry"
    strat = AIFactorStrategy(params={"registry_dir": str(empty_dir)})
    strat._load_model()
    assert strat._model is None
    entries, _ = strat.generate_signals(_df())
    assert entries.any(), "momentum degradation must still produce entries"

    # Seeded paper model with low P(up) blocks momentum entries.
    reg = ModelRegistry(str(WORK / "models"))
    reg.register("m-gate", "RandomForestClassifier", "h", {"decision": "GO", "reason": "ok"})
    strat2 = AIFactorStrategy(params={"registry_dir": str(WORK / "models"), "model_id": "m-gate"})
    strat2._model = _LowProbaModel()
    entries2, _ = strat2.generate_signals(_df())
    assert not entries2.any(), "low P(up) must gate out momentum entries"
    print("step3 ai_factor: PASS (degradation + gating)")


class _LowProbaModel:
    classes_ = np.array([0, 1])

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        return np.tile([0.9, 0.1], (len(features), 1))


def step4_spot_perp() -> None:
    """Symmetric spot-perp signals on synthetic funding/OI."""
    idx = pd.date_range("2026-01-01", periods=60, freq="h")
    df = pd.DataFrame(
        {
            "funding_rate": pd.Series(0.0, index=idx, dtype=float),
            "open_interest": pd.Series(1000.0 + np.arange(60) * 10.0, index=idx, dtype=float),
        },
        index=idx,
    )
    df.loc[df.index[27], "open_interest"] *= 0.90  # OI drop > 5% at bar 30
    df.loc[df.index[30], "funding_rate"] = -0.002  # extreme negative
    strat = SpotPerpArbStrategy()
    entries, _ = strat.generate_signals(df)
    assert entries.iloc[30] == 1, "negative funding extreme → long perp"
    spot = strat.spot_leg()
    assert (spot == -entries).all(), "spot leg must mirror perp leg"
    print("step4 spot_perp: PASS (symmetric prototype)")


def main() -> None:
    step1_dynamic_budget()
    step2_auto_loop()
    step3_ai_factor_strategy()
    step4_spot_perp()
    print("s4 pipeline: ALL STEPS PASS")


if __name__ == "__main__":
    main()
