"""Auto research loop — backtest → validate → register/reject (s4 T-s4-02).

Closes the s3 AI-research loop: a candidate model is trained with
:class:`quantflow.strategy.ai_training.AITrainingPipeline`, validated by the
standard ``validation_gate``, and then either registered in the
:class:`quantflow.strategy.model_registry.ModelRegistry` (decision == "GO",
status = paper) or rejected (decision != "GO"). Every decision is appended to
a JSONL decision log so the loop is auditable end-to-end.

The loop is deliberately orchestration-only: training, validation, and the
registry gate are the s3 building blocks (no reimplementation). YAML-driven
via ``ai.auto_loop`` (default OFF).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.common.config import AutoLoopConfigModel

logger = logging.getLogger(__name__)


@dataclass
class AutoLoopDecision:
    """One loop iteration's outcome (auditable record)."""

    model_id: str
    model_cls: str
    features_hash: str
    decision: str  # GO | NO-GO
    reason: str
    n_samples: int
    metrics: dict[str, Any] = field(default_factory=dict)
    decided_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_cls": self.model_cls,
            "features_hash": self.features_hash,
            "decision": self.decision,
            "reason": self.reason,
            "n_samples": self.n_samples,
            "metrics": self.metrics,
            "decided_at": self.decided_at,
        }


class AutoResearchLoop:
    """Orchestrate one training → validation → registration iteration.

    Usage::

        loop = AutoResearchLoop(registry=ModelRegistry("data/models"))
        decision = loop.run_once(features, close, model_cls=RandomForestClassifier)
        # decision.decision == "GO" → registry entry status=paper
        # decision.decision == "NO-GO" → no registry entry (fail-closed)
    """

    def __init__(
        self,
        registry: Any,
        config: AutoLoopConfigModel | None = None,
        training_pipeline: Any | None = None,
    ) -> None:
        self._registry = registry
        self._config = config or AutoLoopConfigModel()
        self._pipeline = training_pipeline

    def run_once(
        self,
        features: pd.DataFrame,
        close: pd.Series,
        model_cls: Any,
        **model_kwargs: Any,
    ) -> AutoLoopDecision:
        """Run one full iteration: train → validate → register/reject.

        Args:
            features: Feature matrix (index aligned to ``close``).
            close: Close-price series (label source).
            model_cls: sklearn-style classifier class.
            **model_kwargs: Constructor kwargs for the model.

        Returns:
            AutoLoopDecision with ``decision`` = GO (registered, paper) or
            NO-GO (rejected, logged).
        """
        from quantflow.strategy.ai_training import AITrainingPipeline

        pipeline = self._pipeline or AITrainingPipeline(**self._config.training_kwargs)
        report = pipeline.train(features, close, model_cls, **model_kwargs)

        if not report.model_id:
            report.model_id = self._registry.new_id()
        validation: dict[str, Any] = report.validation or {}

        # Fail-closed: registry refuses anything without decision == "GO".
        entry = self._registry.register(
            model_id=report.model_id,
            model_cls=report.model_cls,
            features_hash=report.features_hash,
            validation_report=validation,
        )
        status = entry.get("status", "rejected")
        is_go = status == "paper"
        decision = AutoLoopDecision(
            model_id=report.model_id,
            model_cls=report.model_cls,
            features_hash=report.features_hash,
            decision="GO" if is_go else "NO-GO",
            reason=str(entry.get("reason", "registry refused")),
            n_samples=report.n_samples,
            metrics={
                "gate_checks": _metric_summary(validation),
                "feature_importance": report.feature_importance,
            },
            decided_at=self._now(),
        )
        self._append_log(decision)
        logger.info(
            "auto_loop: model=%s decision=%s (%s)", report.model_id, decision.decision, decision.reason
        )
        return decision

    def _append_log(self, decision: AutoLoopDecision) -> None:
        """Append one decision record to the JSONL log (append-only, atomic-ish)."""
        path = Path(self._config.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()


def _metric_summary(validation: dict[str, Any]) -> dict[str, Any]:
    """Compact, JSON-safe summary of gate checks for the decision log."""
    out: dict[str, Any] = {}
    checks = validation.get("checks")
    if isinstance(checks, dict):
        for name, res in checks.items():
            if isinstance(res, dict):
                keep = {
                    k: res[k]
                    for k in ("passed", "pbo", "dsr", "oos_efficiency", "avg_win_rate")
                    if k in res
                }
                out[name] = keep
    if "decision" in validation:
        out["decision"] = validation["decision"]
    return out
