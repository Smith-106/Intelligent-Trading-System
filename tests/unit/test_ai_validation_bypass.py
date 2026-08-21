"""T036: AI validation bypass — no live wire."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.ai_validation_bypass import (
    AI_LANE,
    AILiveWireError,
    assert_ai_live_not_wired,
    run_ai_validation_bypass,
    stamp_ai_bypass_report,
)
from quantflow.strategy.model_registry import ModelRegistry, ModelRegistryError
from quantflow.strategy.validation.cost_fidelity import build_funding_tca


def _ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 100 * np.exp(np.cumsum(rng.standard_normal(n) * 0.01))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": rng.random(n) + 1.0,
            "timestamp": (idx.astype(np.int64) // 10**6).astype(np.int64),
        },
        index=idx,
    )


def test_stamp_marks_lane() -> None:
    out = stamp_ai_bypass_report({"decision": "GO", "validation": {}})
    assert out["ai_lane"] == AI_LANE
    assert out["ai_live_blocked"] is True
    assert out["validation"]["execution_path"] == "vectorized"


def test_assert_blocks_live() -> None:
    with pytest.raises(AILiveWireError):
        assert_ai_live_not_wired({"ai_lane": AI_LANE, "status": "paper"})


def test_run_bypass_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # isolate factor/report dirs under tmp
    import quantflow.strategy.ai_validation_bypass as bypass
    import quantflow.strategy.rd_agent as rd

    monkeypatch.setattr(bypass, "BYPASS_REPORT_DIR", tmp_path / "ai_reports")
    monkeypatch.setattr(rd, "FACTORS_DIR", tmp_path / "ai_factors")

    result = run_ai_validation_bypass(
        symbol="BTC/USDT",
        ohlcv=_ohlcv(),
        register=False,
    )
    assert result.ai_live_blocked is True
    assert result.ai_lane == AI_LANE
    assert Path(result.report_path).exists()
    payload = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert payload["ai_live_blocked"] is True
    assert payload["validation"]["ai_lane"] == AI_LANE


def test_promote_to_live_refuses_bypass_entry(tmp_path: Path) -> None:
    reg = ModelRegistry(str(tmp_path / "reg"))
    # Manually write a paper entry stamped as AI bypass (simulate bad path).
    entry = {
        "model_id": "m-ai",
        "model_cls": "X",
        "features_hash": "h",
        "status": "paper",
        "decision": "GO",
        "ai_lane": AI_LANE,
        "ai_live_blocked": True,
        "registered_at": "t",
    }
    (tmp_path / "reg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reg" / "m-ai.json").write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="validation_bypass"):
        reg.promote_to_live(
            "m-ai",
            paper_evidence={"paper_days": 30.0, "fills": 50},
        )


def test_register_vectorized_ai_rejected_by_w14(tmp_path: Path) -> None:
    """Even with cost grid, vectorized execution_path must fail W14."""
    reg = ModelRegistry(str(tmp_path / "reg"))
    report = {
        "decision": "GO",
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 10.0},
            {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.5, "return_pct": 5.0},
        ],
        "funding_tca": build_funding_tca(mode="assumption"),
        "execution_path": "vectorized",
        "data_fingerprint": {"aggregate": "x"},
        "ai_lane": AI_LANE,
        "ai_live_blocked": True,
    }
    entry = reg.register("m-v", "X", "h", report)
    assert entry["status"] == "rejected"
