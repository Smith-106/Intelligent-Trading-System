"""Multi-source pause reasons (OSS learning: binance-deribit-btc pause set).

Subsystems add/remove independent reasons; trading is paused while the set
is non-empty. Avoids single-bool flags overwriting each other.

Not a product change to cross-venue arb — only the control pattern.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PauseReasonSet:
    """Set-driven pause controller.

    Example::

        pauses = PauseReasonSet()
        pauses.add("data_stale")
        pauses.add("kill_switch")
        assert pauses.is_paused
        pauses.remove("data_stale")
        assert pauses.is_paused  # kill_switch still active
        pauses.remove("kill_switch")
        assert not pauses.is_paused
    """

    _reasons: set[str] = field(default_factory=set)
    _manual: bool = False

    def add(self, reason: str) -> None:
        text = str(reason or "").strip()
        if text:
            self._reasons.add(text)

    def remove(self, reason: str) -> None:
        self._reasons.discard(str(reason or "").strip())

    def clear(self) -> None:
        self._reasons.clear()
        self._manual = False

    def set_manual_stop(self, active: bool = True) -> None:
        """Operator stop; only cleared by set_manual_stop(False)."""
        self._manual = bool(active)

    @property
    def is_paused(self) -> bool:
        return self._manual or bool(self._reasons)

    @property
    def reasons(self) -> frozenset[str]:
        out = set(self._reasons)
        if self._manual:
            out.add("manual_stop")
        return frozenset(out)

    def snapshot(self) -> dict[str, Any]:
        return {
            "paused": self.is_paused,
            "reasons": sorted(self.reasons),
            "manual_stop": self._manual,
        }

    def replace(self, reasons: Iterable[str]) -> None:
        self._reasons = {str(r).strip() for r in reasons if str(r).strip()}
