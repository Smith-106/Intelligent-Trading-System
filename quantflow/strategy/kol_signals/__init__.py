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
from quantflow.strategy.kol_signals.reference_weight import (
    MarketAssessment,
    ReferenceWeightConfig,
    SymbolReference,
    apply_reference_to_notional,
    build_reference_snapshot,
    load_consensus_reports,
    market_assessment,
    reference_multiplier,
)
from quantflow.strategy.kol_signals.registry import load_kol_registry

__all__ = [
    "AttachmentMeta",
    "ConsensusReport",
    "KolSignal",
    "KolSource",
    "MarketAssessment",
    "ReferenceWeightConfig",
    "SignalSide",
    "SymbolReference",
    "aggregate_consensus",
    "apply_reference_to_notional",
    "build_reference_snapshot",
    "load_consensus_reports",
    "load_kol_registry",
    "market_assessment",
    "parse_trade_text",
    "reference_multiplier",
]
