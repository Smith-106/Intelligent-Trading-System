"""Wave identification data models.

Core data structures for Elliott Wave pattern identification:
- WavePattern: IMPULSE (1-5) or CORRECTIVE (A-B-C)
- AnalysisMode: RETROSPECTIVE (strict) or PROGRESSIVE (lenient)
- WaveSegment: A single wave within a pattern
- WaveCount: Complete wave count with current state
- IronLawResult: Three iron laws validation result
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from quantflow.indicators.zigzag import PivotDirection, PivotPoint


class WavePattern(str, Enum):
    IMPULSE = "impulse"
    CORRECTIVE = "corrective"
    UNKNOWN = "unknown"


class AnalysisMode(str, Enum):
    RETROSPECTIVE = "retrospective"
    PROGRESSIVE = "progressive"


@dataclass
class WaveSegment:
    """A single wave within an Elliott Wave pattern."""
    label: int  # 1-5 for impulse, -1/-2/-3 for A-B-C
    start: PivotPoint
    end: PivotPoint
    length_pct: float = 0.0  # price change as percentage
    retracement_pct: float | None = None  # retracement of previous wave

    def price_range(self) -> tuple[float, float]:
        lo = min(self.start.price, self.end.price)
        hi = max(self.start.price, self.end.price)
        return lo, hi

    def amplitude(self) -> float:
        return abs(self.end.price - self.start.price)


@dataclass
class WaveCount:
    """Complete wave count with current state and iron-law validation.

    WaveCount is the core data structure flowing through L2→L3→L4,
    providing wave context for strategy decisions and risk management.
    """
    pattern: WavePattern = WavePattern.UNKNOWN
    current_wave: int = 0
    waves: dict[int, WaveSegment] = field(default_factory=dict)
    mode: AnalysisMode = AnalysisMode.PROGRESSIVE
    confidence: float = 0.0  # 0.0-1.0

    def get_wave(self, label: int) -> WaveSegment | None:
        return self.waves.get(label)

    def critical_levels(self) -> dict[str, float]:
        """Extract critical price levels from current wave count."""
        levels: dict[str, float] = {}
        if w1 := self.waves.get(1):
            levels["w1_start"] = w1.start.price
            levels["w1_end"] = w1.end.price
        if w3 := self.waves.get(3):
            levels["w3_end"] = w3.end.price
        if w4 := self.waves.get(4):
            levels["w4_end"] = w4.end.price
        return levels


@dataclass
class IronLawResult:
    """Result of validating a WaveCount against the three iron laws.

    Iron Law 1: W2 cannot retrace below W1 start (enforced in both modes).
    Iron Law 2: W3 cannot be the shortest of W1/W3/W5
        (RETROSPECTIVE: enforced; PROGRESSIVE: checked+warning only per C-001).
    Iron Law 3: W4 cannot enter W1 price territory (enforced in both modes,
        diagonal exception flagged).
    """
    law1_ok: bool = True
    law2_ok: bool | None = None  # None = not yet determinable
    law2_mode: AnalysisMode = AnalysisMode.PROGRESSIVE
    law3_ok: bool = True
    law3_diagonal: bool = False  # diagonal triangle exception
    warnings: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True if no violations in the current enforcement mode."""
        if not self.law1_ok:
            return False
        if self.law2_mode == AnalysisMode.RETROSPECTIVE and self.law2_ok is False:
            return False
        if not self.law3_ok and not self.law3_diagonal:
            return False
        return True

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
