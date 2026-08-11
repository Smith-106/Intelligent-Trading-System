"""KOL / Discord signal aggregation (advisory, not auto-copy by default).

Ingest → parse (text + optional chart OCR) → score sources → consensus
window → optional RiskEngine handoff. Live copy-trading is explicitly out
of scope unless a future contract enables it with paper evidence.
"""

from __future__ import annotations

from quantflow.strategy.kol_signals.aggregator import (
    ConsensusReport,
    aggregate_consensus,
)
from quantflow.strategy.kol_signals.models import (
    AttachmentMeta,
    KolSignal,
    KolSource,
    SignalSide,
)
from quantflow.strategy.kol_signals.parser import parse_trade_text
from quantflow.strategy.kol_signals.registry import load_kol_registry

__all__ = [
    "AttachmentMeta",
    "ConsensusReport",
    "KolSignal",
    "KolSource",
    "SignalSide",
    "aggregate_consensus",
    "load_kol_registry",
    "parse_trade_text",
]
