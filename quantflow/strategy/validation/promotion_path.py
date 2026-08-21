"""Promotion execution-path discipline (Option B / W14).

GO / registry paper registration must cite a **production-path** evaluation
(``paper_replay`` / ``TradingSession`` event path), not a vectorized-only
BacktestEngine or VectorBT poster.

Rationale (architecture-diagnosis-vs-oss.md):
  - Parity scope is paper↔live; backtest is a separate research filter.
  - Cost-honest promotion requires the same L4/L5 path paper will run.
  - Fail-closed: missing or vectorized-only path → refuse register.

Attach on the validation report (any of):

```json
{
  "execution_path": "paper_replay",
  "data_fingerprint": {"aggregate": "…"}
}
```

or under ``checks.execution_path`` / ``run_meta.execution_path``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Paths that may carry a GO narrative into ModelRegistry.register.
ALLOWED_EXECUTION_PATHS = frozenset(
    {
        "paper_replay",
        "trading_session",
        "event_session",
        "production_path",
    }
)

# Explicitly refused for standalone promotion (research filter only).
REFUSED_EXECUTION_PATHS = frozenset(
    {
        "vectorized",
        "backtest_engine",
        "backtest",
        "vectorbt",
        "vbt",
        "optuna_only",
        "hyperopt",
    }
)


class PromotionPathError(ValueError):
    """Raised when execution-path / fingerprint requirements fail (W14)."""


def _as_dict(report: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(report) if isinstance(report, Mapping) else {}


def extract_execution_path(report: Mapping[str, Any] | None) -> str | None:
    """Pull normalized execution_path from a validation / run report."""
    raw = _as_dict(report)
    candidates: list[Any] = [
        raw.get("execution_path"),
        raw.get("research_path"),
        raw.get("eval_path"),
    ]
    checks = raw.get("checks")
    if isinstance(checks, dict):
        candidates.append(checks.get("execution_path"))
        path_block = checks.get("promotion_path")
        if isinstance(path_block, dict):
            candidates.append(path_block.get("execution_path"))
    run_meta = raw.get("run_meta")
    if isinstance(run_meta, dict):
        candidates.append(run_meta.get("execution_path"))
    artifacts = raw.get("artifacts")
    if isinstance(artifacts, dict):
        candidates.append(artifacts.get("execution_path"))

    for c in candidates:
        if c is None:
            continue
        text = str(c).strip().lower().replace("-", "_").replace(" ", "_")
        if text:
            return text
    return None


def extract_data_fingerprint(
    report: Mapping[str, Any] | None,
) -> dict[str, Any] | str | None:
    """Pull data_fingerprint / contract pin hash if present."""
    raw = _as_dict(report)
    for key in ("data_fingerprint", "fingerprint", "bar_fingerprint"):
        val = raw.get(key)
        if isinstance(val, (dict, str)) and val:
            return val
    checks = raw.get("checks")
    if isinstance(checks, dict):
        for key in ("data_fingerprint", "fingerprint"):
            val = checks.get(key)
            if isinstance(val, (dict, str)) and val:
                return val
        path_block = checks.get("promotion_path")
        if isinstance(path_block, dict):
            val = path_block.get("data_fingerprint")
            if isinstance(val, (dict, str)) and val:
                return val
    run_meta = raw.get("run_meta")
    if isinstance(run_meta, dict):
        val = run_meta.get("data_fingerprint")
        if isinstance(val, (dict, str)) and val:
            return val
    pin = raw.get("contract_pin")
    if isinstance(pin, dict):
        val = pin.get("data_fingerprint")
        if isinstance(val, (dict, str)) and val:
            return val
    return None


def check_promotion_path(
    report: Mapping[str, Any] | None,
    *,
    require_fingerprint: bool = True,
) -> dict[str, Any]:
    """Evaluate path discipline; never raises (structured result)."""
    path = extract_execution_path(report)
    fp = extract_data_fingerprint(report)
    result: dict[str, Any] = {
        "passed": True,
        "execution_path": path,
        "data_fingerprint_present": fp is not None,
        "require_fingerprint": require_fingerprint,
        "reasons": [],
        "rule": (
            "GO/register requires execution_path in "
            f"{sorted(ALLOWED_EXECUTION_PATHS)}; "
            "vectorized/backtest_engine alone is refused (W14)"
        ),
    }

    if path is None:
        result["passed"] = False
        result["reasons"].append(
            "execution_path missing: attach paper_replay/trading_session "
            "provenance on the validation report (W14 fail-closed)"
        )
        return result

    if path in REFUSED_EXECUTION_PATHS:
        result["passed"] = False
        result["reasons"].append(
            f"execution_path={path!r} is research-filter only; "
            "re-run GO metrics on paper_replay / TradingSession (W14)"
        )
        return result

    if path not in ALLOWED_EXECUTION_PATHS:
        result["passed"] = False
        result["reasons"].append(
            f"execution_path={path!r} not in allowed {sorted(ALLOWED_EXECUTION_PATHS)} (W14)"
        )
        return result

    if require_fingerprint and fp is None:
        result["passed"] = False
        result["reasons"].append(
            "data_fingerprint missing: pin OHLCV used for GO (contract_pin / run_meta; T011+W14)"
        )
        return result

    return result


def assert_promotion_path_ready(
    report: Mapping[str, Any] | None,
    *,
    require_fingerprint: bool = True,
) -> dict[str, Any]:
    """Fail-closed promotion path gate (W14)."""
    result = check_promotion_path(report, require_fingerprint=require_fingerprint)
    if not result.get("passed", False):
        reasons = result.get("reasons") or ["promotion path failed"]
        raise PromotionPathError("; ".join(str(r) for r in reasons))
    return result


def attach_promotion_path(
    validation_report: dict[str, Any],
    *,
    execution_path: str = "paper_replay",
    data_fingerprint: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Shallow-copy report with promotion path fields for GO narratives."""
    out = dict(validation_report)
    out["execution_path"] = str(execution_path).strip().lower()
    if data_fingerprint is not None:
        out["data_fingerprint"] = data_fingerprint
    checks = dict(out.get("checks") or {})
    checks["promotion_path"] = {
        "execution_path": out["execution_path"],
        "data_fingerprint": data_fingerprint,
        "rule": "W14 paper_replay-or-equivalent required for register",
    }
    out["checks"] = checks
    return out
