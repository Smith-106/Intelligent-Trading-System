"""Day-session deviation checks vs Baseline-0 artifacts (T017).

Path A (daily paper) and Path B (nested gate / Baseline-0 WFO) are **not**
comparable as raw PnL. This module checks:

1. **Contract health** (always): gate decision, required artifacts, pin meta.
2. **Optional PnL snapshot** (diagnostic only): if a day paper report is
   supplied, compare return/DD bands against Baseline full-window metrics
   with an explicit ``path_a_ne_path_b`` flag — never treat equality as
   required for GO.

Alerts fire when health fails or optional PnL band is breached **and** the
caller enables alerting.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_GATE_PATH = Path("data/paper_replay/baseline0/gate.json")
DEFAULT_META_PATH = Path("data/paper_replay/baseline0/run_meta.json")
DEFAULT_FULL_PATH = Path("data/paper_replay/baseline0/multi_symbol_replay.json")

# Soft bands for optional Path A diagnostic vs Path B full RP metrics.
# These are *not* promotion criteria — Path A ≠ Path B by design.
DEFAULT_RETURN_BAND_PP = 50.0  # percentage points absolute
DEFAULT_DD_BAND_PP = 25.0


@dataclass(frozen=True)
class DeviationThresholds:
    return_band_pp: float = DEFAULT_RETURN_BAND_PP
    max_dd_band_pp: float = DEFAULT_DD_BAND_PP
    require_paper_go: bool = True
    require_artifacts: bool = True


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_baseline_snapshot(
    *,
    repo_root: Path | None = None,
    gate_path: Path | str | None = None,
    meta_path: Path | str | None = None,
    full_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load Baseline-0 gate + meta + full RP metrics for day-session attach."""
    root = repo_root or Path.cwd()
    gate_p = Path(gate_path) if gate_path else root / DEFAULT_GATE_PATH
    meta_p = Path(meta_path) if meta_path else root / DEFAULT_META_PATH
    full_p = Path(full_path) if full_path else root / DEFAULT_FULL_PATH
    if not gate_p.is_absolute():
        gate_p = root / gate_p
    if not meta_p.is_absolute():
        meta_p = root / meta_p
    if not full_p.is_absolute():
        full_p = root / full_p

    gate = _load_json(gate_p)
    meta = _load_json(meta_p)
    full = _load_json(full_p)

    rp = None
    if isinstance(full, dict):
        rp = full.get("shared_risk_parity")
        if not isinstance(rp, dict):
            rp = full.get("metrics") if isinstance(full.get("metrics"), dict) else None

    metrics = {}
    if isinstance(gate, dict) and isinstance(gate.get("metrics"), dict):
        metrics = dict(gate["metrics"])
    if isinstance(rp, dict):
        metrics.setdefault("full_return_pct", rp.get("return_pct"))
        metrics.setdefault("full_sharpe", rp.get("sharpe_annualized"))
        metrics.setdefault("full_max_dd_pct", rp.get("max_drawdown_pct"))
        metrics.setdefault("full_orders", rp.get("orders") or rp.get("fills"))

    return {
        "gate_path": str(gate_p),
        "meta_path": str(meta_p),
        "full_path": str(full_p),
        "gate_present": gate is not None,
        "meta_present": meta is not None,
        "full_present": full is not None,
        "decision": (gate or {}).get("decision"),
        "baseline_id": (gate or {}).get("baseline_id", "Baseline-0"),
        "metrics": metrics,
        "window": {
            "start": (meta or {}).get("start"),
            "end": (meta or {}).get("end"),
            "data_fingerprint": (meta or {}).get("data_fingerprint"),
        },
        "path_note": (
            "Path A day-session PnL is NOT comparable to Path B nested gate / "
            "Baseline-0 WFO numbers (T017)."
        ),
    }


def evaluate_day_deviation(
    *,
    baseline: Mapping[str, Any] | None = None,
    day_metrics: Mapping[str, Any] | None = None,
    thresholds: DeviationThresholds | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Compute deviation report for a day-session summary.

    Parameters
    ----------
    baseline:
        Snapshot from ``load_baseline_snapshot`` (loaded if omitted).
    day_metrics:
        Optional Path A paper numbers: ``return_pct``, ``max_drawdown_pct``,
        ``sharpe_annualized``. When absent, only contract health is checked.
    """
    thr = thresholds or DeviationThresholds()
    snap = dict(baseline) if baseline is not None else load_baseline_snapshot(repo_root=repo_root)

    issues: list[str] = []
    alerts: list[dict[str, Any]] = []

    # --- contract health ---
    if thr.require_artifacts:
        if not snap.get("gate_present"):
            issues.append("baseline gate.json missing")
            alerts.append(
                {
                    "level": "error",
                    "code": "BASELINE_GATE_MISSING",
                    "message": "Baseline-0 gate.json not found — Path B snapshot unavailable",
                }
            )
        if not snap.get("meta_present"):
            issues.append("baseline run_meta.json missing")
            alerts.append(
                {
                    "level": "warning",
                    "code": "BASELINE_META_MISSING",
                    "message": "Baseline-0 run_meta.json missing (pin/fingerprint unknown)",
                }
            )

    decision = snap.get("decision")
    if thr.require_paper_go and snap.get("gate_present"):
        if decision not in ("PAPER-GO", "GO"):
            issues.append(f"baseline decision={decision!r} (expected PAPER-GO)")
            alerts.append(
                {
                    "level": "error",
                    "code": "BASELINE_NOT_PAPER_GO",
                    "message": f"Baseline decision is {decision!r}, not PAPER-GO",
                }
            )

    # --- optional Path A diagnostic band ---
    pnl_block: dict[str, Any] | None = None
    if day_metrics:
        b_metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
        day_ret = _as_float(day_metrics.get("return_pct"))
        base_ret = _as_float(b_metrics.get("full_return_pct"))
        day_dd = _as_float(day_metrics.get("max_drawdown_pct"))
        base_dd = _as_float(b_metrics.get("full_max_dd_pct"))

        ret_delta = None
        dd_delta = None
        ret_breach = False
        dd_breach = False
        if day_ret is not None and base_ret is not None:
            ret_delta = day_ret - base_ret
            ret_breach = abs(ret_delta) > thr.return_band_pp
        if day_dd is not None and base_dd is not None:
            dd_delta = day_dd - base_dd
            # Day DD much worse than baseline full DD (higher drawdown magnitude)
            dd_breach = (day_dd - base_dd) > thr.max_dd_band_pp

        pnl_block = {
            "comparable": False,
            "path_a_ne_path_b": True,
            "day": {
                "return_pct": day_ret,
                "max_drawdown_pct": day_dd,
                "sharpe_annualized": _as_float(day_metrics.get("sharpe_annualized")),
            },
            "baseline_full_rp": {
                "return_pct": base_ret,
                "max_drawdown_pct": base_dd,
                "sharpe_annualized": _as_float(b_metrics.get("full_sharpe")),
            },
            "delta": {
                "return_pp": ret_delta,
                "max_dd_pp": dd_delta,
            },
            "bands_pp": {
                "return": thr.return_band_pp,
                "max_dd": thr.max_dd_band_pp,
            },
            "breaches": {
                "return": ret_breach,
                "max_dd": dd_breach,
            },
            "note": (
                "Diagnostic only: Path A daily paper must not be scored against "
                "Path B nested Baseline-0 WFO. Large deltas may still warrant ops review."
            ),
        }
        if ret_breach:
            issues.append(
                f"diagnostic return delta {ret_delta:+.1f}pp exceeds ±{thr.return_band_pp}pp"
            )
            alerts.append(
                {
                    "level": "warning",
                    "code": "DAY_RETURN_BAND",
                    "message": (
                        f"Path A return {day_ret} vs Baseline full RP {base_ret} "
                        f"(Δ{ret_delta:+.1f}pp) — not a gate fail; ops review"
                    ),
                }
            )
        if dd_breach:
            issues.append(f"diagnostic DD delta {dd_delta:+.1f}pp exceeds +{thr.max_dd_band_pp}pp")
            alerts.append(
                {
                    "level": "warning",
                    "code": "DAY_DD_BAND",
                    "message": (
                        f"Path A maxDD {day_dd} vs Baseline full RP {base_dd} "
                        f"(Δ{dd_delta:+.1f}pp) — ops review"
                    ),
                }
            )

    health_ok = not any(a.get("level") == "error" for a in alerts)
    # warnings alone → status=degraded; errors → alert
    if not health_ok:
        status = "alert"
    elif alerts:
        status = "degraded"
    else:
        status = "ok"

    return {
        "kind": "day_baseline_deviation",
        "task": "T017",
        "status": status,
        "health_ok": health_ok,
        "should_alert": status in ("alert", "degraded"),
        "baseline": {
            "id": snap.get("baseline_id"),
            "decision": decision,
            "gate_present": snap.get("gate_present"),
            "meta_present": snap.get("meta_present"),
            "window": snap.get("window"),
            "metrics": snap.get("metrics"),
            "path_note": snap.get("path_note"),
        },
        "pnl_diagnostic": pnl_block,
        "issues": issues,
        "alerts": alerts,
        "thresholds": asdict(thr),
    }


def format_alert_message(report: Mapping[str, Any]) -> str:
    """One-line / multi-line alert body for Telegram/LINE hooks."""
    status = report.get("status", "?")
    decision = (report.get("baseline") or {}).get("decision")
    issues = report.get("issues") or []
    lines = [
        f"[QuantFlow day-deviation] status={status} baseline_decision={decision}",
    ]
    for issue in issues[:5]:
        lines.append(f"  - {issue}")
    if report.get("pnl_diagnostic"):
        lines.append("  (Path A ≠ Path B; PnL band is diagnostic only)")
    return "\n".join(lines)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
