"""Tests for AutoResearchLoop — s4 T-s4-02 (backtest → validate → register/reject)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.common.config import AutoLoopConfigModel
from quantflow.strategy.ai_training import TrainedModelReport
from quantflow.strategy.auto_loop import AutoResearchLoop
from quantflow.strategy.model_registry import ModelRegistry


class _FakeRegistry:
    """Minimal registry double: records register() calls; never registers."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.ids: list[str] = []

    def new_id(self) -> str:
        return f"fake-{len(self.ids)}"

    def register(
        self, model_id: str, model_cls: str, features_hash: str, validation_report: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "model_id": model_id,
                "model_cls": model_cls,
                "features_hash": features_hash,
                "validation_report": validation_report,
            }
        )
        decision = str(validation_report.get("decision", "NO-GO"))
        return {
            "model_id": model_id,
            "status": "paper" if decision == "GO" else "rejected",
            "reason": "gate passed" if decision == "GO" else "gate refused",
        }


class _FakePipeline:
    """Pipeline double with scripted report."""

    def __init__(self, report: TrainedModelReport) -> None:
        self._report = report

    def train(
        self, features: pd.DataFrame, close: pd.Series, model_cls: Any, **kwargs: Any
    ) -> TrainedModelReport:
        return self._report


def _report(decision: str, reason: str = "gate ran", model_id: str = "") -> TrainedModelReport:
    return TrainedModelReport(
        model_id=model_id,
        model_cls="FakeModel",
        features_hash="abc123",
        n_samples=500,
        validation={
            "decision": decision,
            "reason": reason,
            "checks": {"cpcv": {"passed": decision == "GO"}},
        },
        decision=decision,
        reason=reason,
        trained_at="2026-08-04T00:00:00+00:00",
    )


def _features_close(n: int = 100) -> tuple[pd.DataFrame, pd.Series]:
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    rng = pd.DataFrame(
        {
            "rsi": pd.Series([50.0 + (i % 10) for i in range(n)], dtype=float, index=idx),
            "atr": pd.Series(1.0, dtype=float, index=idx),
        },
        index=idx,
    )
    close = pd.Series([100.0 + (i % 5) for i in range(n)], index=idx, dtype=float)
    return rng, close


class TestAutoResearchLoopGO:
    def test_go_registers_paper_and_logs(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        log = tmp_path / "decisions.jsonl"
        loop = AutoResearchLoop(
            registry=registry,
            config=AutoLoopConfigModel(log_path=str(log)),
            training_pipeline=_FakePipeline(_report("GO", model_id="")),
        )
        decision = loop.run_once(*_features_close(), model_cls=object)
        assert decision.decision == "GO"
        assert decision.reason == "gate passed"
        assert registry.calls[0]["model_id"] == "fake-0"
        # Log written append-only with full metadata.
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["decision"] == "GO"
        assert record["model_id"] == "fake-0"
        assert record["n_samples"] == 500
        assert "gate_checks" in record["metrics"]
        assert "decided_at" in record


class TestAutoResearchLoopNOGO:
    def test_nogo_logs_rejection(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        log = tmp_path / "decisions.jsonl"
        loop = AutoResearchLoop(
            registry=registry,
            config=AutoLoopConfigModel(log_path=str(log)),
            training_pipeline=_FakePipeline(_report("NO-GO", reason="PBO=0.6", model_id="m-1")),
        )
        decision = loop.run_once(*_features_close(), model_cls=object)
        assert decision.decision == "NO-GO"
        assert decision.reason == "gate refused"
        # Registry still received the call (fail-closed decision inside registry).
        assert registry.calls[0]["model_id"] == "m-1"
        record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
        assert record["decision"] == "NO-GO"

    def test_existing_model_id_preserved(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        loop = AutoResearchLoop(
            registry=registry,
            config=AutoLoopConfigModel(log_path=str(tmp_path / "d.jsonl")),
            training_pipeline=_FakePipeline(_report("GO", model_id="custom-id")),
        )
        decision = loop.run_once(*_features_close(), model_cls=object)
        assert decision.model_id == "custom-id"
        assert registry.calls[0]["model_id"] == "custom-id"


class TestAutoResearchLoopIntegration:
    def test_full_loop_with_real_pipeline_and_registry(self, tmp_path: Path) -> None:
        """End-to-end with the real AITrainingPipeline + ModelRegistry.

        Synthetic random data cannot pass the validation gate, so the expected
        outcome is NO-GO → rejected entry + logged decision (fail-closed)."""
        registry = ModelRegistry(str(tmp_path / "models"))
        log = tmp_path / "decisions.jsonl"
        cfg = AutoLoopConfigModel(
            log_path=str(log),
            training_kwargs={"test_size": 0.3, "random_state": 1},
            validation_kwargs={
                "n_trials": 5,
                "cpcv_groups": 3,
                "cpcv_test_groups": 1,
                "wfo_windows": 2,
            },
        )
        loop = AutoResearchLoop(registry=registry, config=cfg)
        idx = pd.date_range("2026-01-01", periods=300, freq="h")
        rng = pd.DataFrame({"rsi": pd.Series(50.0, index=idx, dtype=float)}, index=idx)
        close = pd.Series(100.0, index=idx, dtype=float)

        from sklearn.ensemble import RandomForestClassifier

        decision = loop.run_once(rng, close, RandomForestClassifier, n_estimators=5)
        assert decision.decision == "NO-GO"
        # Registry has a rejected entry under the generated id.
        entries = registry.list_models()
        assert len(entries) == 1
        assert entries[0]["model_id"] == decision.model_id
        assert entries[0]["status"] == "rejected"
        # Log file exists with one record.
        assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 1

    def test_log_appends_across_iterations(self, tmp_path: Path) -> None:
        registry = _FakeRegistry()
        log = tmp_path / "decisions.jsonl"
        loop = AutoResearchLoop(
            registry=registry,
            config=AutoLoopConfigModel(log_path=str(log)),
            training_pipeline=_FakePipeline(_report("GO")),
        )
        loop.run_once(*_features_close(), model_cls=object)
        loop.run_once(*_features_close(), model_cls=object)
        assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 2
