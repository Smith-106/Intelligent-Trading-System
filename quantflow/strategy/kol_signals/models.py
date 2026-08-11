"""KOL signal data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class SignalSide(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    UNKNOWN = "unknown"


@dataclass
class KolSource:
    """One KOL / channel / webhook source in the registry."""

    source_id: str
    display_name: str = ""
    platform: str = "discord"  # discord | telegram | manual
    channel_ids: list[str] = field(default_factory=list)
    weight: float = 1.0
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttachmentMeta:
    """Image / file attachment (often TradingView screenshots)."""

    url: str = ""
    local_path: str = ""
    content_type: str = ""
    filename: str = ""
    ocr_text: str = ""
    ocr_backend: str = ""  # none | tesseract | vision_api | stub
    is_chart_likely: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KolSignal:
    """Normalized signal extracted from a social message."""

    signal_id: str
    source_id: str
    platform: str
    channel_id: str
    message_id: str
    author: str
    created_at_ms: int
    raw_text: str
    side: SignalSide = SignalSide.UNKNOWN
    symbol: str = ""
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: list[float] = field(default_factory=list)
    timeframe: str = ""
    confidence: float = 0.0  # parser confidence 0..1
    weight: float = 1.0  # source weight
    attachments: list[AttachmentMeta] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KolSignal:
        side_raw = data.get("side", "unknown")
        try:
            side = SignalSide(str(side_raw))
        except ValueError:
            side = SignalSide.UNKNOWN
        atts = [
            AttachmentMeta(**a) if isinstance(a, dict) else a
            for a in (data.get("attachments") or [])
        ]
        return cls(
            signal_id=str(data.get("signal_id", "")),
            source_id=str(data.get("source_id", "")),
            platform=str(data.get("platform", "")),
            channel_id=str(data.get("channel_id", "")),
            message_id=str(data.get("message_id", "")),
            author=str(data.get("author", "")),
            created_at_ms=int(data.get("created_at_ms") or 0),
            raw_text=str(data.get("raw_text", "")),
            side=side,
            symbol=str(data.get("symbol", "") or ""),
            entry=_opt_float(data.get("entry")),
            stop_loss=_opt_float(data.get("stop_loss")),
            take_profit=[float(x) for x in (data.get("take_profit") or []) if x is not None],
            timeframe=str(data.get("timeframe", "") or ""),
            confidence=float(data.get("confidence") or 0.0),
            weight=float(data.get("weight") or 1.0),
            attachments=atts,
            parse_notes=list(data.get("parse_notes") or []),
            meta=dict(data.get("meta") or {}),
        )


def _opt_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
