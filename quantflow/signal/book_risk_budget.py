"""Three-layer book risk budget (factor sleeve → strategy → book).

Maps High-Flyer-style organization (factor pool → strategy factory → risk budget
+ kill) onto QuantFlow's personal-scale stack without claiming institutional
compute parity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BookRiskBudget:
    """Hierarchical notional caps as fractions of book equity.

    Parameters
    ----------
    book_gross_limit
        Max sum of absolute notionals / equity (e.g. 1.0 = 100% gross).
    book_net_limit
        Max |net long-short| / equity.
    strategy_limits
        Per-strategy_id max |notional| / equity.
    factor_sleeve_limits
        Optional sleeve caps (e.g. {"beta": 1.0, "overlay": 0.2}).
    kill_drawdown
        If book drawdown (0-1) reaches this, reject all risk-increasing orders.
    """

    book_gross_limit: float = 1.0
    book_net_limit: float = 1.0
    strategy_limits: dict[str, float] = field(default_factory=dict)
    factor_sleeve_limits: dict[str, float] = field(default_factory=dict)
    kill_drawdown: float = 0.15

    def __post_init__(self) -> None:
        if self.book_gross_limit <= 0:
            raise ValueError("book_gross_limit must be > 0")
        if self.book_net_limit <= 0:
            raise ValueError("book_net_limit must be > 0")
        if not (0 < self.kill_drawdown <= 1):
            raise ValueError("kill_drawdown must be in (0, 1]")
        for name, lim in {**self.strategy_limits, **self.factor_sleeve_limits}.items():
            if lim < 0:
                raise ValueError(f"limit for {name!r} must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def check(
        self,
        *,
        equity: float,
        current_gross: float,
        current_net: float,
        proposed_notional_delta: float,
        strategy_id: str | None = None,
        strategy_current_notional: float = 0.0,
        sleeve: str | None = None,
        sleeve_current_notional: float = 0.0,
        current_drawdown: float = 0.0,
        risk_increasing: bool = True,
    ) -> dict[str, Any]:
        """Return {allowed, reason, layers[]}.

        ``proposed_notional_delta`` is signed change in position notional
        (positive = add long exposure). Gross uses absolute notionals.
        """
        layers: list[dict[str, Any]] = []
        if equity <= 0:
            return {
                "allowed": False,
                "reason": "non_positive_equity",
                "layers": layers,
            }

        dd = abs(float(current_drawdown))
        if risk_increasing and dd >= self.kill_drawdown:
            layers.append(
                {
                    "layer": "kill_drawdown",
                    "limit": self.kill_drawdown,
                    "value": dd,
                    "ok": False,
                }
            )
            return {
                "allowed": False,
                "reason": "kill_drawdown",
                "layers": layers,
            }
        layers.append(
            {
                "layer": "kill_drawdown",
                "limit": self.kill_drawdown,
                "value": dd,
                "ok": True,
            }
        )

        # projected gross: approximate |current| + |delta| for increasing risk
        delta = float(proposed_notional_delta)
        proj_gross = abs(float(current_gross)) + abs(delta)
        gross_ok = proj_gross <= self.book_gross_limit * equity + 1e-9
        layers.append(
            {
                "layer": "book_gross",
                "limit": self.book_gross_limit * equity,
                "value": proj_gross,
                "ok": gross_ok,
            }
        )
        if not gross_ok:
            return {"allowed": False, "reason": "book_gross", "layers": layers}

        proj_net = float(current_net) + delta
        net_ok = abs(proj_net) <= self.book_net_limit * equity + 1e-9
        layers.append(
            {
                "layer": "book_net",
                "limit": self.book_net_limit * equity,
                "value": proj_net,
                "ok": net_ok,
            }
        )
        if not net_ok:
            return {"allowed": False, "reason": "book_net", "layers": layers}

        if strategy_id and strategy_id in self.strategy_limits:
            lim = self.strategy_limits[strategy_id] * equity
            proj = abs(float(strategy_current_notional) + delta)
            ok = proj <= lim + 1e-9
            layers.append(
                {
                    "layer": "strategy",
                    "strategy_id": strategy_id,
                    "limit": lim,
                    "value": proj,
                    "ok": ok,
                }
            )
            if not ok:
                return {"allowed": False, "reason": "strategy_limit", "layers": layers}

        if sleeve and sleeve in self.factor_sleeve_limits:
            lim = self.factor_sleeve_limits[sleeve] * equity
            proj = abs(float(sleeve_current_notional) + delta)
            ok = proj <= lim + 1e-9
            layers.append(
                {
                    "layer": "factor_sleeve",
                    "sleeve": sleeve,
                    "limit": lim,
                    "value": proj,
                    "ok": ok,
                }
            )
            if not ok:
                return {"allowed": False, "reason": "sleeve_limit", "layers": layers}

        return {"allowed": True, "reason": "ok", "layers": layers}


def default_highflyer_style_budget(
    *,
    overlay_sleeve: float = 0.20,
    beta_sleeve: float = 1.0,
    kill_drawdown: float = 0.15,
) -> BookRiskBudget:
    """Personal-scale default: full beta sleeve + capped overlay + DD kill."""
    return BookRiskBudget(
        book_gross_limit=1.0 + overlay_sleeve,
        book_net_limit=1.0 + overlay_sleeve,
        strategy_limits={},
        factor_sleeve_limits={"beta": beta_sleeve, "overlay": overlay_sleeve},
        kill_drawdown=kill_drawdown,
    )
