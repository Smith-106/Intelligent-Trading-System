"""Unified dual-path research report (Path A overlay + Path B TPSL).

Never merges paths into combined_score / composite_score for decision.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT_ID = "DUAL-PATH-RESEARCH-OS-20260811"
FORBIDDEN_DECISION_KEYS = frozenset(
    {"combined_score", "composite_score", "best_score", "merged_score"}
)

DEFAULT_HONESTY = (
    "paths not combinable",
    "no combined_score",
    "path_a continuous overlay is not pen-trade winrate",
    "path_b discrete TPSL is not continuous beta sleeve",
    "pin-window metrics are cost-aware research, not pure OOS claims",
    "promotion_eligible defaults false",
)


@dataclass
class DualPathResearchReport:
    """Envelope for dual-path research outputs."""

    contract: str = CONTRACT_ID
    run_meta: dict[str, Any] = field(default_factory=dict)
    paths: dict[str, Any] = field(default_factory=dict)
    attachments: dict[str, Any] = field(default_factory=dict)
    honesty: list[str] = field(default_factory=lambda: list(DEFAULT_HONESTY))
    complete: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        assert_no_combined_score(d)
        return d


def assert_no_combined_score(obj: Any, *, _path: str = "$") -> None:
    """Raise if forbidden decision keys appear as dict keys anywhere."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_DECISION_KEYS:
                raise ValueError(f"forbidden decision key {k!r} at {_path}.{k}")
            assert_no_combined_score(v, _path=f"{_path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            assert_no_combined_score(item, _path=f"{_path}[{i}]")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def build_dual_path_report(
    *,
    path_a: dict[str, Any],
    path_b: dict[str, Any],
    run_meta: dict[str, Any] | None = None,
    attachments: dict[str, Any] | None = None,
    honesty: list[str] | None = None,
    complete: bool = True,
) -> DualPathResearchReport:
    """Assemble dual-path report; forces promotion_eligible false on both paths."""
    a = dict(path_a)
    b = dict(path_b)
    a.setdefault("kind", "continuous_overlay")
    b.setdefault("kind", "discrete_tpsl")
    a["promotion_eligible"] = False
    b["promotion_eligible"] = False
    meta = {
        "generated_at": _utc_now(),
        "python_utf8": True,
        **(run_meta or {}),
    }
    report = DualPathResearchReport(
        contract=CONTRACT_ID,
        run_meta=meta,
        paths={"path_a": a, "path_b": b},
        attachments=dict(attachments or {}),
        honesty=list(honesty) if honesty is not None else list(DEFAULT_HONESTY),
        complete=complete,
    )
    assert_no_combined_score(report.to_dict())
    return report


def from_overlay_eval(
    overlay: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map overlay eval / primary_overlay block to path_a metrics."""
    # Accept either nested primary_overlay_reduce_off or flat keys
    block = overlay.get("primary_overlay_reduce_off") or overlay.get("path_a") or overlay
    meta = block.get("meta") if isinstance(block.get("meta"), dict) else {}
    metrics = {
        "return_pct": block.get("return_pct"),
        "excess_return_pct": block.get("excess_return_pct"),
        "max_dd_pct": block.get("max_dd_pct"),
        "gate_vs_btc": block.get("gate") or block.get("gate_vs_btc"),
        "beats_btc": block.get("beats_btc"),
    }
    return {
        "kind": "continuous_overlay",
        "profile": profile or meta or {},
        "metrics": metrics,
        "promotion_eligible": False,
    }


def from_tpsl_eval(
    tpsl: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map TPSL eval block (tpsl_default / recommended / flat) to path_b."""
    block = (
        tpsl.get("tpsl_default")
        or tpsl.get("best_score")
        or tpsl.get("path_b")
        or tpsl
    )
    # Never promote research_rank / score into decision
    trade_stats = block.get("trade_stats") or {}
    metrics = {
        "return_pct": block.get("return_pct"),
        "excess_return_pct": block.get("excess_return_pct"),
        "max_dd_pct": block.get("max_dd_pct"),
        "sharpe": block.get("sharpe"),
        "gate_vs_btc": block.get("gate") or block.get("gate_vs_btc"),
        "beats_btc": block.get("beats_btc"),
        "winrate": trade_stats.get("winrate"),
        "payoff_ratio": trade_stats.get("payoff_ratio"),
        "n_trades": trade_stats.get("n_trades") or block.get("n_trades"),
        "exit_reasons": block.get("exit_reasons"),
    }
    cfg = block.get("config") if isinstance(block.get("config"), dict) else {}
    return {
        "kind": "discrete_tpsl",
        "profile": profile or cfg,
        "metrics": metrics,
        "execution_models": {"tpsl_simulator": True},
        "promotion_eligible": False,
    }


def to_json(report: DualPathResearchReport, *, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, ensure_ascii=False) + "\n"


def to_markdown(report: DualPathResearchReport) -> str:
    d = report.to_dict()
    a = d["paths"].get("path_a") or {}
    b = d["paths"].get("path_b") or {}
    am = a.get("metrics") or {}
    bm = b.get("metrics") or {}
    lines = [
        "# Dual-Path Research Report",
        "",
        f"**Contract**: `{d.get('contract')}`",
        f"**Generated**: {d.get('run_meta', {}).get('generated_at', '')}",
        f"**Complete**: {d.get('complete')}",
        "",
        "## Path A — continuous overlay (excess flagship)",
        "",
        f"- kind: `{a.get('kind')}`",
        f"- promotion_eligible: `{a.get('promotion_eligible')}`",
        f"- return_pct: {am.get('return_pct')}",
        f"- excess_return_pct: {am.get('excess_return_pct')}",
        f"- max_dd_pct: {am.get('max_dd_pct')}",
        f"- gate_vs_btc: {am.get('gate_vs_btc')}",
        "",
        "## Path B — discrete TPSL (DD / R:R control)",
        "",
        f"- kind: `{b.get('kind')}`",
        f"- promotion_eligible: `{b.get('promotion_eligible')}`",
        f"- return_pct: {bm.get('return_pct')}",
        f"- excess_return_pct: {bm.get('excess_return_pct')}",
        f"- max_dd_pct: {bm.get('max_dd_pct')}",
        f"- winrate: {bm.get('winrate')}",
        f"- payoff_ratio: {bm.get('payoff_ratio')}",
        f"- gate_vs_btc: {bm.get('gate_vs_btc')}",
        "",
        "## Honesty",
        "",
    ]
    for h in d.get("honesty") or []:
        lines.append(f"- {h}")
    lines.append("")
    lines.append("## Forbidden")
    lines.append("")
    lines.append("- No `combined_score` / `composite_score` / `best_score` decision fields.")
    lines.append("")
    if d.get("attachments"):
        lines.append("## Attachments")
        lines.append("")
        for k in d["attachments"]:
            lines.append(f"- `{k}`")
        lines.append("")
    return "\n".join(lines)


def write_report(
    report: DualPathResearchReport,
    out_json: Path | str,
    *,
    out_md: Path | str | None = None,
) -> tuple[Path, Path | None]:
    """Write JSON (+ optional MD). Returns written paths."""
    jp = Path(out_json)
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(to_json(report), encoding="utf-8")
    mp: Path | None = None
    if out_md is not None:
        mp = Path(out_md)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(to_markdown(report), encoding="utf-8")
    return jp, mp
