"""L6 research GO panel loader — fail-soft export of the sealed performance panel.

Reads the sealed source of truth ``data/paper_replay/perf_verify/
performance_panel.json`` and normalizes the primary research GO fields
(``baseline0_gate`` + ``shared_risk_parity``) into a typed snapshot for
Prometheus gauges / the thin CLI export. L6-only: this module must NOT be
imported from ``quantflow/strategy`` / ``quantflow/research``, and it never
recomputes ``multi_symbol_replay`` (see fingerprint skip policy in
``.workflow/knowhow/DOC-research-go-panel-export.md``).

Fail-soft contract: missing file, JSON decode error, or missing required keys
yield ``None`` with a warning log — never invented metrics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Repo-root-anchored default so the loader works regardless of the process CWD
# (same spirit as scripts that resolve REPO_ROOT from ``__file__``).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_RESEARCH_GO_PANEL_PATH = (
    REPO_ROOT / "data" / "paper_replay" / "perf_verify" / "performance_panel.json"
)

# path_semantics keys we copy verbatim when present (no invented narrative).
_PATH_SEMANTICS_KEYS = (
    "multi_symbol_replay",
    "beta_overlay_dual_path",
    "parity_note",
)

# Numeric primary fields required from the gate metrics (or the
# portfolio_modes[primary_mode] fallback).
_PRIMARY_METRIC_KEYS = (
    "full_return_pct",
    "full_sharpe",
    "full_max_dd_pct",
    "full_orders",
)
_PORTFOLIO_MODE_FALLBACK_KEYS = {
    "full_return_pct": "return_pct",
    "full_sharpe": "sharpe_annualized",
    "full_max_dd_pct": "max_drawdown_pct",
    "full_orders": "orders",
}

_PAPER_GO_DECISION = "PAPER-GO"


@dataclass
class ResearchGoPanelSnapshot:
    """Typed export of the sealed research GO panel (L6, fail-soft loaded).

    ``promotion_eligible`` is ALWAYS ``False`` — research GO export is not a
    live-promotion signal (locks.no_live_promote), regardless of any
    ``promotion_eligible_any_research`` value in the source panel.
    """

    decision: str
    primary_mode: str
    full_return_pct: float
    full_sharpe: float
    full_max_dd_pct: float
    full_orders: float
    data_fingerprint_aggregate: str
    as_of: str
    path_semantics: dict[str, Any] = field(default_factory=dict)
    promotion_eligible: bool = False
    source_path: str = ""
    loaded_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable export for the CLI / downstream consumers."""
        return asdict(self)


def _coerce_float(key: str, value: Any) -> float | None:
    """Coerce a panel number to float; None when missing/invalid (fail-soft)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_primary_numbers(
    gate_metrics: dict[str, Any] | None,
    portfolio_modes: dict[str, Any] | None,
    primary_mode: str,
) -> dict[str, float] | None:
    """Primary numbers from gate metrics, falling back to the mode block.

    Prefers ``baseline0_gate.metrics.full_*``; when those are absent, falls
    back to ``portfolio_modes[primary_mode]`` equivalents. Returns None when
    neither source yields all four numbers (fail-soft, no invented metrics).
    """
    numbers: dict[str, float] = {}
    if gate_metrics:
        for key in _PRIMARY_METRIC_KEYS:
            if key in gate_metrics:
                val = _coerce_float(key, gate_metrics[key])
                if val is not None:
                    numbers[key] = val
    if len(numbers) < len(_PRIMARY_METRIC_KEYS) and portfolio_modes:
        mode_block = portfolio_modes.get(primary_mode)
        if isinstance(mode_block, dict):
            for key in _PRIMARY_METRIC_KEYS:
                if key in numbers:
                    continue
                fallback_key = _PORTFOLIO_MODE_FALLBACK_KEYS[key]
                val = _coerce_float(key, mode_block.get(fallback_key))
                if val is not None:
                    numbers[key] = val
    if len(numbers) < len(_PRIMARY_METRIC_KEYS):
        return None
    return numbers


def load_research_go_panel(
    path: str | Path | None = None,
) -> ResearchGoPanelSnapshot | None:
    """Load + normalize the sealed research GO panel; None on any failure.

    Resolution: ``None`` → the sealed default SoT path; a relative path is
    resolved against the repo root (consistent with scripts). Fail-soft on
    missing file, JSON decode errors, non-dict payload, missing
    ``baseline0_gate``, or missing primary numbers — each logs a warning and
    returns None instead of fabricating metrics.
    """
    panel_path = Path(path) if path is not None else DEFAULT_RESEARCH_GO_PANEL_PATH
    if not panel_path.is_absolute():
        panel_path = REPO_ROOT / panel_path
    if not panel_path.is_file():
        logger.warning(
            "research GO panel not found at %s — fail-soft None (no metrics)",
            panel_path,
        )
        return None
    try:
        raw = json.loads(panel_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "research GO panel %s unreadable/invalid JSON (%s) — fail-soft None",
            panel_path,
            exc,
        )
        return None
    if not isinstance(raw, dict):
        logger.warning("research GO panel %s is not a JSON object — fail-soft None", panel_path)
        return None

    gate = raw.get("baseline0_gate")
    if not isinstance(gate, dict):
        logger.warning("research GO panel %s missing baseline0_gate — fail-soft None", panel_path)
        return None
    decision = gate.get("decision")
    primary_mode = gate.get("primary_mode")
    if (
        not isinstance(decision, str)
        or not decision
        or not isinstance(primary_mode, str)
        or not primary_mode
    ):
        logger.warning(
            "research GO panel %s missing decision/primary_mode — fail-soft None",
            panel_path,
        )
        return None

    gate_metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else None
    portfolio_modes = raw.get("portfolio_modes")
    portfolio_modes = portfolio_modes if isinstance(portfolio_modes, dict) else None
    numbers = _extract_primary_numbers(gate_metrics, portfolio_modes, primary_mode)
    if numbers is None:
        logger.warning(
            "research GO panel %s missing primary numbers for %r — fail-soft None",
            panel_path,
            primary_mode,
        )
        return None

    path_semantics: dict[str, Any] = {}
    raw_ps = raw.get("path_semantics")
    if isinstance(raw_ps, dict):
        for key in _PATH_SEMANTICS_KEYS:
            if key in raw_ps:
                path_semantics[key] = raw_ps[key]

    return ResearchGoPanelSnapshot(
        decision=decision,
        primary_mode=primary_mode,
        full_return_pct=numbers["full_return_pct"],
        full_sharpe=numbers["full_sharpe"],
        full_max_dd_pct=numbers["full_max_dd_pct"],
        full_orders=numbers["full_orders"],
        data_fingerprint_aggregate=str(raw.get("data_fingerprint_aggregate") or ""),
        as_of=str(raw.get("as_of") or ""),
        path_semantics=path_semantics,
        promotion_eligible=False,  # research GO export is never a promote signal
        source_path=str(panel_path),
        loaded_ok=True,
    )
