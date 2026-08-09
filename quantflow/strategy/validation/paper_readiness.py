"""Paper session minimum sample / duration gate (T016).

Before paper→live promotion (and optionally paper registration when
``paper_evidence`` is supplied), require:

- minimum calendar days of paper session coverage
- minimum fill / order count

Defaults are on and fail-closed. Thresholds are overridable via
``PaperReadinessConfig`` / YAML ``risk.paper_readiness``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Mapping


class PaperReadinessError(ValueError):
    """Raised when paper sample/duration thresholds are not met."""


@dataclass(frozen=True)
class PaperReadinessConfig:
    """Configurable paper promotion floors (T016)."""

    enabled: bool = True
    min_paper_days: float = 7.0
    min_fills: int = 20
    min_orders: int = 0  # 0 = do not enforce orders separately
    # If True, missing paper_evidence fails when enabled (strict promote path).
    require_evidence: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> PaperReadinessConfig:
        if not raw:
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", True)),
            min_paper_days=float(raw.get("min_paper_days", 7.0)),
            min_fills=int(raw.get("min_fills", 20)),
            min_orders=int(raw.get("min_orders", 0)),
            require_evidence=bool(raw.get("require_evidence", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    # Support trailing Z
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def extract_paper_evidence(report: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Pull paper_evidence / paper_session block from a validation or registry report."""
    if not isinstance(report, dict):
        return None
    for key in ("paper_evidence", "paper_session", "paper_stats"):
        block = report.get(key)
        if isinstance(block, dict) and block:
            return dict(block)
    validation = report.get("validation")
    if isinstance(validation, dict):
        for key in ("paper_evidence", "paper_session"):
            block = validation.get(key)
            if isinstance(block, dict) and block:
                return dict(block)
    return None


def measure_paper_days(evidence: Mapping[str, Any]) -> float | None:
    """Return paper coverage in days from evidence fields.

    Accepts explicit ``paper_days`` / ``duration_days``, or
    ``started_at``+``ended_at`` / ``start_ms``+``end_ms``.
    """
    for key in ("paper_days", "duration_days", "days"):
        if evidence.get(key) is not None:
            try:
                return float(evidence[key])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

    start = _parse_ts(evidence.get("started_at") or evidence.get("start"))
    end = _parse_ts(evidence.get("ended_at") or evidence.get("end") or evidence.get("finished_at"))
    if start and end and end >= start:
        return (end - start).total_seconds() / 86400.0

    try:
        s_ms = evidence.get("start_ms")
        e_ms = evidence.get("end_ms")
        if s_ms is not None and e_ms is not None:
            return max(0.0, (int(e_ms) - int(s_ms)) / 86_400_000.0)
    except (TypeError, ValueError):
        return None
    return None


def measure_fills(evidence: Mapping[str, Any]) -> int | None:
    for key in ("fills", "n_fills", "fill_count", "num_fills"):
        if evidence.get(key) is not None:
            try:
                return int(evidence[key])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
    return None


def measure_orders(evidence: Mapping[str, Any]) -> int | None:
    for key in ("orders", "n_orders", "order_count", "num_orders"):
        if evidence.get(key) is not None:
            try:
                return int(evidence[key])  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
    return None


def check_paper_readiness(
    evidence: Mapping[str, Any] | None,
    *,
    config: PaperReadinessConfig | None = None,
) -> dict[str, Any]:
    """Evaluate paper sample floors; return structured result (never raises)."""
    cfg = config or PaperReadinessConfig()
    result: dict[str, Any] = {
        "passed": True,
        "enabled": cfg.enabled,
        "config": cfg.to_dict(),
        "reasons": [],
        "measured": {},
    }
    if not cfg.enabled:
        result["skipped"] = True
        return result

    if not evidence:
        if cfg.require_evidence:
            result["passed"] = False
            result["reasons"].append(
                "paper_evidence missing: need paper_days/fills for promotion (T016)"
            )
        return result

    days = measure_paper_days(evidence)
    fills = measure_fills(evidence)
    orders = measure_orders(evidence)
    result["measured"] = {
        "paper_days": days,
        "fills": fills,
        "orders": orders,
    }

    if days is None:
        result["passed"] = False
        result["reasons"].append(
            "paper_days unmeasurable: provide paper_days or started_at/ended_at (T016)"
        )
    elif days < cfg.min_paper_days:
        result["passed"] = False
        result["reasons"].append(
            f"paper_days={days:.2f} < min_paper_days={cfg.min_paper_days} (T016)"
        )

    if fills is None:
        result["passed"] = False
        result["reasons"].append(
            "fills unmeasurable: provide fills/n_fills in paper_evidence (T016)"
        )
    elif fills < cfg.min_fills:
        result["passed"] = False
        result["reasons"].append(
            f"fills={fills} < min_fills={cfg.min_fills} (T016)"
        )

    if cfg.min_orders > 0:
        if orders is None:
            result["passed"] = False
            result["reasons"].append(
                "orders unmeasurable: provide orders when min_orders>0 (T016)"
            )
        elif orders < cfg.min_orders:
            result["passed"] = False
            result["reasons"].append(
                f"orders={orders} < min_orders={cfg.min_orders} (T016)"
            )

    return result


def assert_paper_readiness(
    evidence: Mapping[str, Any] | None,
    *,
    config: PaperReadinessConfig | None = None,
) -> dict[str, Any]:
    """Fail-closed paper sample gate (T016)."""
    result = check_paper_readiness(evidence, config=config)
    if not result.get("passed", False):
        reasons = result.get("reasons") or ["paper readiness failed"]
        raise PaperReadinessError("; ".join(str(r) for r in reasons))
    return result


def assert_report_paper_ready(
    report: Mapping[str, Any] | None,
    *,
    config: PaperReadinessConfig | None = None,
    require_when_missing: bool | None = None,
) -> dict[str, Any]:
    """Run paper readiness against a validation/registry report.

    If ``require_when_missing`` is False and no evidence is attached, skip
    (used on initial GO→paper register when only research gate is available).
    Promote-to-live should pass ``require_when_missing=True`` (default via config).
    """
    cfg = config or PaperReadinessConfig()
    if require_when_missing is not None:
        cfg = PaperReadinessConfig(
            enabled=cfg.enabled,
            min_paper_days=cfg.min_paper_days,
            min_fills=cfg.min_fills,
            min_orders=cfg.min_orders,
            require_evidence=require_when_missing,
        )
    evidence = extract_paper_evidence(report)
    return assert_paper_readiness(evidence, config=cfg)
