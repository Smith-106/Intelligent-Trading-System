"""Ghost / untracked position detection (OSS learning: GhostMixin pattern).

Compare exchange-visible positions to the set of symbols the strategy book
tracks. Untracked non-dust positions are "ghosts" — often residual legs or
manual fills. Does **not** auto-close; returns a structured report for
operators / recon drills.

Default-safe: pure function, no network, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from quantflow.common.validators import POSITION_EPSILON


@dataclass
class GhostPositionReport:
    """Result of comparing exchange positions vs tracked symbols."""

    ghosts: list[dict[str, Any]] = field(default_factory=list)
    tracked_with_position: list[str] = field(default_factory=list)
    missing_on_exchange: list[str] = field(default_factory=list)
    dust_ignored: list[str] = field(default_factory=list)

    @property
    def has_ghosts(self) -> bool:
        return bool(self.ghosts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_ghosts": self.has_ghosts,
            "ghosts": list(self.ghosts),
            "tracked_with_position": list(self.tracked_with_position),
            "missing_on_exchange": list(self.missing_on_exchange),
            "dust_ignored": list(self.dust_ignored),
        }


def _qty(pos: Any) -> float:
    if pos is None:
        return 0.0
    if isinstance(pos, Mapping):
        return float(pos.get("quantity", pos.get("size", 0.0)) or 0.0)
    return float(getattr(pos, "quantity", getattr(pos, "size", 0.0)) or 0.0)


def _symbol(pos: Any) -> str:
    if isinstance(pos, Mapping):
        return str(pos.get("symbol", pos.get("instrument", "")) or "")
    return str(getattr(pos, "symbol", getattr(pos, "instrument_name", "")) or "")


def find_ghost_positions(
    *,
    tracked_symbols: Iterable[str],
    exchange_positions: Iterable[Any],
    dust: float = POSITION_EPSILON,
) -> GhostPositionReport:
    """Return untracked exchange positions and missing tracked holdings.

    Parameters
    ----------
    tracked_symbols:
        Symbols the internal book expects to own (open strategy legs).
    exchange_positions:
        Iterable of Position-like objects or dicts from gateway.query_positions().
    dust:
        Absolute quantity below which a position is ignored.
    """
    tracked = {str(s).strip() for s in tracked_symbols if str(s).strip()}
    report = GhostPositionReport()
    exchange_by_sym: dict[str, float] = {}

    for pos in exchange_positions:
        sym = _symbol(pos)
        if not sym:
            continue
        q = _qty(pos)
        if abs(q) < dust:
            report.dust_ignored.append(sym)
            continue
        exchange_by_sym[sym] = exchange_by_sym.get(sym, 0.0) + q

    for sym, q in exchange_by_sym.items():
        if sym in tracked:
            report.tracked_with_position.append(sym)
        else:
            report.ghosts.append({"symbol": sym, "quantity": q, "kind": "untracked"})

    for sym in tracked:
        if sym not in exchange_by_sym:
            report.missing_on_exchange.append(sym)

    return report
