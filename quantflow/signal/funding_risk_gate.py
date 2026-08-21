"""Funding rate as a **risk gate** (W21a / W22c) — not an alpha signal.

When |funding_rate| exceeds a configured absolute threshold, new entries
should be blocked (and optionally the kill switch activated). This reuses
meta-feed funding observations already collected by TradingSession.

Default posture: gate **off** (zero behavior change).

**W22c track separation (do not merge with B3):**

- **B3** ``funding_rate`` strategy ``entry_threshold=0.001`` is a **frozen
  research signal contract** (KEEP_B0). Changing it requires a new baseline
  version (B4+), never a silent edit.
- **This module** is a **portfolio / session risk control**
  (``RiskConfig.max_funding_rate_abs``). It may share the same numeric scale
  by coincidence but is **not** the B3 signal parameter and must not be used
  to rewrite B3 adjudication or B0 PAPER-GO history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REASON = "funding_risk_gate"


@dataclass(frozen=True)
class FundingRiskDecision:
    blocked: bool
    reason: str
    funding_rate: float
    threshold: float
    symbol: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "funding_rate": self.funding_rate,
            "threshold": self.threshold,
            "symbol": self.symbol,
        }


def evaluate_funding_risk(
    funding_rate: float | None,
    *,
    enabled: bool = False,
    max_abs: float = 0.001,
    symbol: str = "",
) -> FundingRiskDecision:
    """Return whether funding is too extreme to open new risk.

    Args:
        funding_rate: latest observed rate (fraction per settlement).
        enabled: master switch (default False).
        max_abs: absolute threshold; breach when ``abs(rate) > max_abs``.
        symbol: optional label for logs/events.
    """
    thr = max(0.0, float(max_abs))
    if not enabled:
        return FundingRiskDecision(
            blocked=False,
            reason="",
            funding_rate=float(funding_rate or 0.0),
            threshold=thr,
            symbol=symbol,
        )
    if funding_rate is None:
        # Fail-open for missing observation when gate is on would re-introduce
        # silent trade-through; fail-closed on missing data.
        return FundingRiskDecision(
            blocked=True,
            reason=f"{REASON}:missing_rate",
            funding_rate=float("nan"),
            threshold=thr,
            symbol=symbol,
        )
    rate = float(funding_rate)
    if abs(rate) > thr:
        return FundingRiskDecision(
            blocked=True,
            reason=f"{REASON}:abs_rate={rate:.6f}>thr={thr:.6f}",
            funding_rate=rate,
            threshold=thr,
            symbol=symbol,
        )
    return FundingRiskDecision(
        blocked=False,
        reason="",
        funding_rate=rate,
        threshold=thr,
        symbol=symbol,
    )
