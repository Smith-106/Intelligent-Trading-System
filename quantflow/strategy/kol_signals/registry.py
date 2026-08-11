"""Load KOL source registry from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quantflow.strategy.kol_signals.models import KolSource

DEFAULT_REGISTRY = Path("quantflow/config/kol_registry.yaml")


def load_kol_registry(path: str | Path | None = None) -> list[KolSource]:
    """Load sources from YAML. Missing file → empty list (fail-soft)."""
    p = Path(path) if path else DEFAULT_REGISTRY
    if not p.is_file():
        return []
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML required to load kol registry") from exc

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    items = raw.get("sources") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[KolSource] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("source_id") or row.get("id") or "").strip()
        if not sid:
            continue
        out.append(
            KolSource(
                source_id=sid,
                display_name=str(row.get("display_name") or row.get("name") or sid),
                platform=str(row.get("platform") or "discord"),
                channel_ids=[str(x) for x in (row.get("channel_ids") or [])],
                weight=float(row.get("weight") or 1.0),
                tags=[str(t) for t in (row.get("tags") or [])],
                enabled=bool(row.get("enabled", True)),
                notes=str(row.get("notes") or ""),
            )
        )
    return out


def source_by_channel(
    sources: list[KolSource],
    channel_id: str,
    *,
    platform: str = "discord",
) -> KolSource | None:
    """Map a Discord channel id to a registry source (first match)."""
    cid = str(channel_id)
    for s in sources:
        if not s.enabled:
            continue
        if s.platform != platform:
            continue
        if cid in s.channel_ids or "*" in s.channel_ids:
            return s
    return None


def registry_to_dict(sources: list[KolSource]) -> dict[str, Any]:
    return {"sources": [s.to_dict() for s in sources]}
