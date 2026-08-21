"""T036 — RD-Agent / AI factor **validation bypass** (no live wire).

Lane contract
-------------
``research → materialize factors → train → validation_gate → (optional) paper register``

Hard rules:

1. **Never** call ``ModelRegistry.promote_to_live`` from this module or the
   ``quantflow ai bypass`` CLI path.
2. Artifacts are stamped ``ai_lane=validation_bypass`` and
   ``ai_live_blocked=true`` so later promote attempts fail closed.
3. Paper ``register`` still requires W14 cost + execution_path gates; AI
   vectorized train alone is **not** a production GO path — attach
   ``paper_replay`` provenance only after an event-path re-eval.
4. Missing qlib / rdagent / LLM → baseline degrade (same as ``rd_agent``).

This is Option-B W16 residual T036: research OS side-door, not an execution
engine rewrite.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

AI_LANE = "validation_bypass"
AI_LIVE_BLOCKED = True
BYPASS_REPORT_DIR = Path("data/ai_reports")
BYPASS_SUMMARY_NAME = "ai_bypass_latest.json"


class AILiveWireError(RuntimeError):
    """Raised when AI lane attempts to touch live promotion."""


@dataclass
class AIBypassResult:
    """Structured outcome of one validation-bypass run."""

    symbol: str
    model_id: str
    decision: str
    reason: str
    factors_path: str
    report_path: str
    n_factors: int
    n_selected: int
    n_samples: int
    features_hash: str
    ai_lane: str = AI_LANE
    ai_live_blocked: bool = AI_LIVE_BLOCKED
    registered_status: str = ""  # paper | rejected | skipped
    notes: list[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def stamp_ai_bypass_report(report: dict[str, Any]) -> dict[str, Any]:
    """Stamp a train/validation payload as AI validation-bypass only."""
    out = dict(report)
    out["ai_lane"] = AI_LANE
    out["ai_live_blocked"] = True
    out["live_wire"] = False
    out["promotion_policy"] = {
        "register_paper": "allowed_if_cost_and_path_gates_pass",
        "promote_to_live": "forbidden_from_ai_bypass",
        "execution_path_for_paper_go": "paper_replay_required_W14",
    }
    validation = dict(out.get("validation") or {})
    validation["ai_lane"] = AI_LANE
    validation["ai_live_blocked"] = True
    # Vectorized train is research filter — do not claim paper_replay here.
    validation.setdefault("execution_path", "vectorized")
    validation.setdefault(
        "promotion_requirements",
        {
            "fee_slip_grid": "required for paper register",
            "funding_tca": "required (T014)",
            "execution_path": "paper_replay required for paper GO (W14)",
            "promote_to_live": "blocked for ai_lane=validation_bypass",
        },
    )
    out["validation"] = validation
    return out


def assert_ai_live_not_wired(entry_or_report: dict[str, Any] | None) -> None:
    """Fail closed if an AI bypass artifact is used for live promotion."""
    raw = entry_or_report or {}
    validation = raw.get("validation") if isinstance(raw.get("validation"), dict) else {}
    if (
        raw.get("ai_lane") == AI_LANE
        or raw.get("ai_live_blocked") is True
        or validation.get("ai_lane") == AI_LANE
        or validation.get("ai_live_blocked") is True
    ):
        raise AILiveWireError("AI validation_bypass lane cannot promote_to_live (T036 fail-closed)")


def run_ai_validation_bypass(
    *,
    symbol: str,
    ohlcv: pd.DataFrame,
    register: bool = False,
    registry_dir: str = "data/model_registry",
    factors_json: str | Path | None = None,
    skip_discover: bool = False,
) -> AIBypassResult:
    """Run research→train validation bypass for one symbol.

    Parameters
    ----------
    symbol:
        Trading symbol (e.g. BTC/USDT).
    ohlcv:
        OHLCV frame with at least ``close`` (and columns needed by materialize).
    register:
        If True, attempt ModelRegistry.register (paper/rejected only).
    registry_dir:
        Registry path when register=True.
    factors_json:
        Existing discovery JSON; if None and not skip_discover, run discover.
    skip_discover:
        Use factors_json / latest only (no discover call).
    """
    from quantflow.strategy.ai_training import AITrainingPipeline
    from quantflow.strategy.rd_agent import (
        FACTORS_DIR,
        RDAgentRunner,
        load_discovered_factors,
        materialize_factor_frame,
        save_discovered_factors,
    )

    notes: list[str] = []
    df = ohlcv.copy()
    if "datetime" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("datetime")

    factors_path = ""
    factors: list[Any] = []
    n_selected = 0

    if factors_json is not None and Path(factors_json).exists():
        factors = load_discovered_factors(factors_json)
        factors_path = str(factors_json)
        notes.append(f"loaded factors from {factors_json}")
    elif skip_discover:
        safe = symbol.replace("/", "_").replace("\\", "_")
        latest = FACTORS_DIR / safe / "latest.json"
        if latest.exists():
            factors = load_discovered_factors(latest)
            factors_path = str(latest)
            notes.append(f"loaded latest factors {latest}")
        else:
            notes.append("skip_discover but no latest factors — empty set")
    else:
        runner = RDAgentRunner()
        available, msg = runner.check_available()
        if not available:
            notes.append(
                f"qlib/rdagent unavailable — baseline degrade ({msg.splitlines()[0] if msg else ''})"
            )
        factors = runner.discover_factors(df)
        saved = save_discovered_factors(
            factors, symbol=symbol, source="ai_validation_bypass", train_rows=len(df)
        )
        factors_path = str(saved)
        notes.append(f"discovered+saved → {saved}")

    n_selected = sum(1 for f in factors if getattr(f, "selected", False))
    features = materialize_factor_frame(df, factors, selected_only=True)
    if features is None or features.empty or features.shape[1] == 0:
        features = materialize_factor_frame(df, factors, selected_only=False)
        notes.append("materialize fell back to all factors (or empty)")
    if features is None or features.empty or features.shape[1] == 0:
        # Last resort: single close-return feature so the gate still runs.
        close = df["close"] if "close" in df.columns else df.iloc[:, 3]
        features = pd.DataFrame({"ret1": close.pct_change().fillna(0.0)})
        notes.append("no factor columns — synthetic ret1 feature for gate exercise")

    close = df["close"].reindex(features.index) if "close" in df.columns else features.iloc[:, 0]
    pipe = AITrainingPipeline(
        validation_kwargs={"cpcv_groups": 4, "cpcv_test_groups": 1, "wfo_windows": 3}
    )
    trained = pipe.train(features, close, None, n_estimators=50, max_depth=3)
    model_id = f"model-{trained.features_hash}"
    payload = stamp_ai_bypass_report(trained.to_dict())
    payload["model_id"] = model_id
    payload["symbol"] = symbol
    payload["factors_path"] = factors_path
    payload["created_at"] = datetime.now(UTC).isoformat()

    BYPASS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = BYPASS_REPORT_DIR / f"{model_id}.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    registered_status = "skipped"
    if register:
        from quantflow.strategy.model_registry import ModelRegistry

        validation_report = dict(payload.get("validation") or {})
        validation_report["decision"] = payload.get("decision", "NO-GO")
        validation_report["ai_lane"] = AI_LANE
        validation_report["ai_live_blocked"] = True
        # Intentionally leave execution_path=vectorized so W14 refuses paper GO
        # unless a later paper_replay re-stamp is provided.
        reg = ModelRegistry(registry_dir)
        entry = reg.register(
            model_id=model_id,
            model_cls=str(payload.get("model_cls", "unknown")),
            features_hash=str(payload.get("features_hash", "")),
            validation_report=validation_report,
        )
        # Persist lane stamps on the registry entry file if written as paper.
        entry["ai_lane"] = AI_LANE
        entry["ai_live_blocked"] = True
        entry_path = Path(registry_dir) / f"{model_id}.json"
        if entry_path.exists() or entry.get("status") in {
            "paper",
            "rejected",
        }:  # pragma: no branch — register() always returns paper/rejected
            # Re-write entry with stamps (register already wrote once).
            entry_path.parent.mkdir(parents=True, exist_ok=True)
            entry_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        registered_status = str(entry.get("status", "rejected"))
        notes.append(f"register → {registered_status}: {entry.get('reason', '')}")

    result = AIBypassResult(
        symbol=symbol,
        model_id=model_id,
        decision=str(payload.get("decision", "NO-GO")),
        reason=str(payload.get("reason", "")),
        factors_path=factors_path,
        report_path=str(report_path),
        n_factors=len(factors),
        n_selected=n_selected,
        n_samples=int(payload.get("n_samples", 0) or 0),
        features_hash=str(payload.get("features_hash", "")),
        registered_status=registered_status,
        notes=notes,
        created_at=payload["created_at"],
    )
    summary_path = BYPASS_REPORT_DIR / BYPASS_SUMMARY_NAME
    summary_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "AI validation bypass done model=%s decision=%s live_blocked=True",
        model_id,
        result.decision,
    )
    return result
