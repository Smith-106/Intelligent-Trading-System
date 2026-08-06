"""Portfolio manager — position tracking, mark-to-market, and drawdown monitoring."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from quantflow.common.models import Portfolio, Position, strategy_id_constituents
from quantflow.common.validators import POSITION_EPSILON

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PendingEntry:
    """A single pending exposure reservation (M4-5.1)."""

    symbol: str
    notional: float
    strategy_id: str
    reserved_at_ms: int


@dataclass(frozen=True, slots=True)
class PendingView:
    """Read-only snapshot of pending reservations for risk checks (M4-5.2)."""

    total: float
    by_symbol: dict[str, float]
    by_strategy: dict[str, float]


class PortfolioManager:
    """Track portfolio positions, equity, and drawdown.

    Supports mark-to-market valuation, unrealized P&L calculation,
    and peak/drawdown tracking for risk engine integration.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._positions: dict[str, Position] = {}
        self._peak_equity = initial_capital
        self._current_drawdown = 0.0
        self._allocation: dict[str, float] = {}
        # Cumulative realized PnL from closed legs (ISS-20260720-004 Wave 1).
        # A flip or partial close attributes the closing leg's PnL here so it
        # is observable independently of cash (which still follows trade
        # notional — total cash movement is unchanged vs the prior single-line
        # ``self._cash -= quantity_delta * price``).
        self._realized_pnl: float = 0.0
        # Daily-loss baseline anchor (ISS-20260720-004 Wave 3). Anchored to the
        # first bar's equity of each calendar day by TradingSession.on_bar;
        # NaN means "not yet anchored" (warmup). Wave 1 only declares the field.
        self._daily_baseline: float = float("nan")
        # M4-5.1: pending exposure ledger. Maps order_id → PendingEntry.
        # Reserve before submit, confirm on fill, release on reject/timeout.
        self._pending: dict[str, PendingEntry] = {}
        # s5 (T-s5-02): per-strategy return histories for risk-parity
        # estimation. Populated only when the engine feeds add_strategy_return
        # (portfolio optimization enabled); empty on the default path.
        self._strategy_returns: dict[str, deque[float]] = {}

    # --- Core properties ---

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def realized_pnl(self) -> float:
        """Cumulative realized PnL from closed legs (ISS-20260720-004 Wave 1)."""
        return self._realized_pnl

    @property
    def current_drawdown(self) -> float:
        return self._current_drawdown

    @property
    def positions(self) -> dict[str, Position]:
        return self._positions

    @property
    def equity(self) -> float:
        """Total portfolio equity (cash + position market values)."""
        return self.total_value

    @property
    def portfolio(self) -> Portfolio:
        """Return a Portfolio model snapshot."""
        return Portfolio(
            cash=self._cash,
            positions=dict(self._positions),
            current_drawdown=self._current_drawdown,
            realized_pnl=self._realized_pnl,
            daily_baseline=self._daily_baseline,
            pending_exposure=self.total_pending_exposure,
        )

    @property
    def total_value(self) -> float:
        """Cash + sum of position market values."""
        pos_value = sum(p.market_value for p in self._positions.values())
        return self._cash + pos_value

    # --- Position management ---

    def get_position(self, symbol: str) -> Position | None:
        """Get position for a symbol, or None if not held."""
        return self._positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        """Check if a position exists for the symbol."""
        pos = self._positions.get(symbol)
        return pos is not None and abs(pos.quantity) > POSITION_EPSILON

    def set_position(self, symbol: str, position: Position) -> None:
        """Overwrite a position from an exchange sync (ISS-20260720-004 Wave 2).

        Live sync_positions semantics: the exchange is the source of truth, so
        the local book is overwritten rather than accumulated. This is distinct
        from update_position (which accumulates fills). Used by
        ExecutionEngine.sync_positions via PositionManager.
        """
        self._positions[symbol] = position
        self._refresh_drawdown()

    def update_position(
        self,
        symbol: str,
        quantity_delta: float,
        price: float,
        *,
        fee: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        """Update or create a position after a fill."""
        existing = self._positions.get(symbol)
        if abs(quantity_delta) < POSITION_EPSILON:
            if existing is None:
                self._refresh_drawdown()
                return
            # ISS-20260723-002: route through Position.with_current_price — the
            # unrealized-PnL formula now has a single owner (common/models.py),
            # shared with PaperGateway.update_market_price.
            self._positions[symbol] = existing.with_current_price(price)
            self._refresh_drawdown()
            return

        # Cash follows trade notional directly; fee always reduces equity.
        # Total cash movement is identical to the prior single-line semantics
        # (ISS-20260720-004 Wave 1 conservative path: realized is attributed
        # independently without recomputing cash, so existing cash assertions
        # hold).
        self._cash -= quantity_delta * price
        if fee:
            self._cash -= fee

        if existing is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity_delta,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                strategy_id=strategy_id,
            )
            self._refresh_drawdown()
            return

        # Attribute realized PnL when this fill closes part of the existing
        # leg (delta opposes existing quantity — partial close or flip). The
        # closing qty is the portion of the existing leg that is liquidated;
        # the sign flips for short closes so realized = (entry-price)*qty.
        # Cash is NOT adjusted here — it already followed notional above.
        if existing.quantity * quantity_delta < 0:
            closing_qty = min(abs(quantity_delta), abs(existing.quantity))
            sign = 1.0 if existing.quantity > 0 else -1.0
            self._realized_pnl += (price - existing.entry_price) * closing_qty * sign

        new_qty = existing.quantity + quantity_delta
        if abs(new_qty) < POSITION_EPSILON:
            del self._positions[symbol]
            self._refresh_drawdown()
            return

        if existing.quantity * quantity_delta > 0:
            total_cost = existing.entry_price * abs(existing.quantity) + price * abs(quantity_delta)
            avg_price = total_cost / abs(new_qty)
        else:
            avg_price = price if existing.quantity * new_qty < 0 else existing.entry_price

        upnl = (price - avg_price) * new_qty
        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=new_qty,
            entry_price=avg_price,
            current_price=price,
            unrealized_pnl=upnl,
            strategy_id=existing.strategy_id or strategy_id,
        )
        self._refresh_drawdown()

    # --- Mark-to-market ---

    def update_market_prices(self, prices: dict[str, float]) -> None:
        """Batch-update market prices for all held positions and recalculate P&L."""
        for symbol, price in prices.items():
            pos = self._positions.get(symbol)
            if pos is not None:
                # ISS-20260723-002: single-owner unrealized-PnL formula via
                # Position.with_current_price (shared with PaperGateway).
                self._positions[symbol] = pos.with_current_price(price)

    def mark_to_market(self, price_feed: dict[str, float]) -> dict[str, float]:
        """Mark all positions to market and return unrealized P&L per symbol."""
        self.update_market_prices(price_feed)
        pnl = {s: p.unrealized_pnl for s, p in self._positions.items()}
        self._refresh_drawdown()
        return pnl

    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized P&L across all positions."""
        return sum(p.unrealized_pnl for p in self._positions.values())

    # --- Cash and allocation ---

    def update_cash(self, amount: float) -> None:
        """Adjust cash balance by amount (positive=deposit, negative=withdrawal)."""
        self._cash += amount
        self._refresh_drawdown()

    def set_capital_baseline(self, capital: float) -> None:
        """Reset the initial-capital and peak-equity baseline atomically.

        Used when a session is started with an operator-supplied capital so
        that drawdown is measured against the correct base. Replaces direct
        mutation of private attributes from presentation layers.
        """
        self._initial_capital = capital
        self._peak_equity = max(capital, self.total_value)
        self._current_drawdown = 0.0

    def set_daily_baseline(self, baseline: float) -> None:
        """Anchor the daily-loss baseline (ISS-20260720-004 Wave 3).

        Called by TradingSession.on_bar on the first bar of each calendar
        day. NaN means "not yet anchored" (warmup) and is the value RiskEngine
        treats as ``<=0`` to skip the daily_loss gate. Does not touch
        drawdown — baseline is a loss-gate anchor, not a peak.
        """
        self._daily_baseline = baseline

    def set_allocation(self, allocation: dict[str, float]) -> None:
        """Set target allocation weights per strategy.

        s5 (T-s5-02): also called on every rebalance tick with the freshly
        computed risk-parity weights — no longer a one-time static set.
        """
        self._allocation = dict(allocation)

    def get_strategy_allocation(self, strategy_id: str) -> float:
        """Get allocation weight for a strategy, or 0 if not set.

        A consolidated signal carries a compound ``strategy_id`` (e.g.
        ``"momentum_rotation,trend_following"``). An exact-key lookup would
        miss the joined key and return 0.0, silently dropping the signal's
        sizing to zero (same class of bug as the strategy_budget bypass in
        risk_engine._check_strategy_budget and the win-rate blending in
        position_sizer.size). Expand the compound key and sum the constituent
        weights so consolidated signals keep their combined allocation.
        """
        if not strategy_id:
            return 0.0
        constituents = strategy_id_constituents(strategy_id)
        if not constituents:
            return self._allocation.get(strategy_id, 0.0)
        return sum(self._allocation.get(c, 0.0) for c in constituents)

    @property
    def allocation(self) -> dict[str, float]:
        return self._allocation

    # --- s5 (T-s5-02): per-strategy return tracking + budget utilization ---

    def add_strategy_return(self, strategy_id: str, ret: float, window: int = 30) -> None:
        """Record a realized per-strategy return for risk-parity estimation.

        Isolated per strategy_id (deque maxlen=window) so one strategy's
        history never pollutes another's volatility estimate. No-op effect
        on the default path: the tracker is only consumed when
        ``portfolio_optimization.enabled`` is true.
        """
        if not strategy_id:
            return
        bucket = self._strategy_returns.get(strategy_id)
        if bucket is None:
            bucket = deque(maxlen=max(window, 2))
            self._strategy_returns[strategy_id] = bucket
        bucket.append(float(ret))

    def get_strategy_returns(self) -> dict[str, list[float]]:
        """Snapshot of per-strategy return histories (optimizer input)."""
        return {k: list(v) for k, v in self._strategy_returns.items()}

    def budget_utilization(self) -> dict[str, dict[str, float]]:
        """Per-strategy exposure vs allocation budget (s5 report).

        Returns {strategy_id: {allocated_notional, exposure_notional,
        utilization_pct}}. Utilization > 1.0 means the strategy's current
        positions exceed its allocated budget share.
        """
        total_value = self.total_value
        report: dict[str, dict[str, float]] = {}
        exposure: dict[str, float] = {}
        for pos in self._positions.values():
            if pos.current_price <= 0:
                continue
            constituents = strategy_id_constituents(pos.strategy_id) or [pos.strategy_id]
            pos_value = abs(pos.quantity) * pos.current_price
            for c in constituents:
                exposure[c] = exposure.get(c, 0.0) + pos_value
        for key, weight in self._allocation.items():
            allocated = total_value * weight
            expo = exposure.get(key, 0.0)
            report[key] = {
                "allocated_notional": allocated,
                "exposure_notional": expo,
                "utilization_pct": expo / allocated if allocated > 0 else 0.0,
            }
        return report

    # --- Risk checks ---

    def check_drawdown(self, max_drawdown: float) -> bool:
        """Check if current drawdown is within the allowed limit.

        Args:
            max_drawdown: Maximum allowed drawdown (negative, e.g. -0.10 for 10%).

        Returns:
            True if drawdown is within limits, False if breached.
        """
        return self._current_drawdown > max_drawdown

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of portfolio state."""
        return {
            "cash": self._cash,
            "total_value": self.total_value,
            "equity": self.equity,
            "positions": len(self._positions),
            "drawdown": self._current_drawdown,
            "peak_equity": self._peak_equity,
            "realized_pnl": self._realized_pnl,
        }

    def _refresh_drawdown(self) -> None:
        total = self.total_value
        if total > self._peak_equity:
            self._peak_equity = total
        if self._peak_equity > 0:
            self._current_drawdown = (total - self._peak_equity) / self._peak_equity

    # --- Pending Exposure Ledger (M4-5.1) ---

    def reserve(self, order_id: str, symbol: str, notional: float, strategy_id: str = "") -> None:
        """Freeze notional exposure before order submission.

        MUST be called BEFORE gateway.send_order. Idempotent per order_id
        (re-reserve overwrites — protects against retry paths).
        """
        self._pending[order_id] = PendingEntry(
            symbol=symbol,
            notional=notional,
            strategy_id=strategy_id,
            reserved_at_ms=int(time.time() * 1000),
        )

    def confirm(self, order_id: str) -> None:
        """Release reservation after full fill confirmed.

        The actual position update is handled by update_position (existing path).
        confirm only removes the pending shadow — it does NOT touch cash/positions.
        """
        self._pending.pop(order_id, None)

    def partial_confirm(self, order_id: str, cumulative_filled_notional: float) -> None:
        """Reduce reservation based on cumulative filled notional (M4-5.14).

        Aligns with ccxt cumulative contract: filled_quantity * filled_price
        gives the cumulative notional; remaining = original - cumulative.
        """
        entry = self._pending.get(order_id)
        if entry is None:
            return
        remaining = entry.notional - cumulative_filled_notional
        if remaining <= POSITION_EPSILON:
            del self._pending[order_id]
        else:
            self._pending[order_id] = PendingEntry(
                symbol=entry.symbol,
                notional=remaining,
                strategy_id=entry.strategy_id,
                reserved_at_ms=entry.reserved_at_ms,
            )

    def release(self, order_id: str) -> None:
        """Release reservation on reject/timeout/cancel. Full amount freed."""
        self._pending.pop(order_id, None)

    def release_all(self) -> int:
        """Release all pending reservations (Kill Switch activation). Returns count."""
        count = len(self._pending)
        self._pending.clear()
        return count

    def pending_for_symbol(self, symbol: str) -> float:
        """Sum of reserved notional for a specific symbol."""
        return sum(e.notional for e in self._pending.values() if e.symbol == symbol)

    @property
    def total_pending_exposure(self) -> float:
        """Sum of all reserved notional across symbols."""
        return sum(e.notional for e in self._pending.values())

    def pending_view(self) -> PendingView:
        """Build a read-only snapshot for risk checks (M4-5.2)."""
        by_symbol: dict[str, float] = {}
        by_strategy: dict[str, float] = {}
        for entry in self._pending.values():
            by_symbol[entry.symbol] = by_symbol.get(entry.symbol, 0.0) + entry.notional
            if entry.strategy_id:
                by_strategy[entry.strategy_id] = (
                    by_strategy.get(entry.strategy_id, 0.0) + entry.notional
                )
        return PendingView(
            total=self.total_pending_exposure, by_symbol=by_symbol, by_strategy=by_strategy
        )

    def sweep_stale_pending(self, max_age_ms: int = 120_000) -> list[str]:
        """Release pending entries older than max_age_ms (M4-5.12).

        Returns released order_ids for logging/alerting. Called periodically
        as a last-resort guard when cancel+sync both fail (quadrant D).
        """
        now_ms = int(time.time() * 1000)
        stale = [
            oid
            for oid, entry in self._pending.items()
            if now_ms - entry.reserved_at_ms > max_age_ms
        ]
        for oid in stale:
            entry = self._pending[oid]
            logger.critical(
                "Sweeping stale pending: oid=%s symbol=%s age=%dms (manual review needed)",
                oid,
                entry.symbol,
                now_ms - entry.reserved_at_ms,
            )
            del self._pending[oid]
        return stale
