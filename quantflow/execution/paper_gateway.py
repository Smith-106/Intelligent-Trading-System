"""Paper Gateway — local simulated exchange for paper trading."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import Any

from quantflow.common.models import Order, OrderStatus, Position
from quantflow.common.validators import POSITION_EPSILON, validate_quantity, validate_symbol
from quantflow.execution.gateway_base import GatewayBase, OpenOrder

logger = logging.getLogger(__name__)


class PaperGateway(GatewayBase):
    """Simulated gateway for paper trading with slippage and fees.

    Orders are filled immediately at the current price plus slippage.
    Suitable for strategy validation before going live.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        # Clamp config-driven rates to a sane non-negative range so a malformed
        # config (negative fee / slippage > 1) cannot inflate equity or invert
        # fill direction (SEC-L3). These are simulator parameters, not user
        # input, but defense-in-depth: never trust a raw dict value.
        self._slippage = max(0.0, min(float(cfg.get("slippage", 0.001)), 0.5))
        self._maker_fee = max(0.0, float(cfg.get("maker_fee", 0.0008)))
        self._taker_fee = max(0.0, float(cfg.get("taker_fee", 0.001)))
        self._initial_capital = float(cfg.get("initial_capital", 1_000_000.0))
        # M4-5.15: opt-in partial fill simulation for limit orders. When set
        # (e.g. 0.3), limit orders fill only that fraction on first submission,
        # returning PARTIAL status. Default None = all orders fill completely
        # (existing behavior, byte-for-byte baseline preserved).
        raw_ratio = cfg.get("partial_fill_ratio")
        self._partial_fill_ratio: float | None = (
            max(0.01, min(float(raw_ratio), 0.99)) if raw_ratio is not None else None
        )
        # W16: opt-in BBO (bid/ask) fill model. Default OFF preserves last-price
        # + flat slippage (byte-stable for B0 paper / existing tests).
        # When enabled, market buys fill at ask and sells at bid (optional extra
        # slip still applied). Missing BBO falls back to legacy last-price path.
        ob = cfg.get("orderbook_fill")
        if not isinstance(ob, dict):
            ob = {}
        self._orderbook_fill_enabled = bool(
            cfg.get("orderbook_fill_enabled", ob.get("enabled", False))
        )
        self._orderbook_extra_slip = max(
            0.0,
            min(float(ob.get("extra_slippage", cfg.get("orderbook_extra_slippage", 0.0))), 0.5),
        )
        # ISS-20260720-004 Wave 2: PaperGateway no longer keeps a cash ledger.
        # _positions remains as the gateway's local exchange view (query_positions
        # / reduceOnly caps); cash is owned solely by L4 PortfolioManager.
        self._positions: dict[str, Position] = {}
        self._order_counter = 0
        self._prices: dict[str, float] = {}  # symbol → last known price
        # symbol → (bid, ask) when orderbook fill is used
        self._bbo: dict[str, tuple[float, float]] = {}
        # ISS-003: mock WebSocket subscription task (paper mode simulates a
        # push feed by periodically emitting local position state).
        self._ws_task: asyncio.Task[Any] | None = None

    async def connect(self, config: dict[str, Any] | None = None) -> None:
        self._positions.clear()
        logger.info(
            "PaperGateway connected: slippage=%.4f, taker_fee=%.4f, orderbook_fill=%s",
            self._slippage,
            self._taker_fee,
            self._orderbook_fill_enabled,
        )

    async def disconnect(self) -> None:
        # ISS-003: cancel any active mock WebSocket loop before tearing down
        # so no orphaned task keeps emitting after the session ends.
        if self._ws_task is not None and not self._ws_task.done():
            self._ws_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ws_task
            self._ws_task = None
        logger.info("PaperGateway disconnected. Open positions: %d", len(self._positions))

    async def send_order(self, order: Order) -> str:
        """Simulate order fill with slippage and fees."""
        # Symmetric choke point with OKXGateway (odyssey-review SEC finding):
        # validate quantity/symbol here too so a NaN/malformed value from the
        # paper signal path cannot reach fill math (notional = price * quantity)
        # and propagate NaN equity into the snapshot/JSONL persistence path.
        validate_quantity(order.quantity)
        validate_symbol(order.symbol)
        self._order_counter += 1
        order_id = f"paper-{self._order_counter}"

        symbol = order.symbol
        side = order.side.value
        quantity = order.quantity
        price = order.price

        fill_price = self._resolve_fill_price(symbol, side, order_price=price)
        if fill_price <= 0:
            # No reference price: reject explicitly and log so the dropped order
            # is visible (CORR-L3 — the previous path set REJECTED silently,
            # making a stream of failed fills look like inactivity).
            logger.warning(
                "Paper order REJECTED: no fill price for %s (order_id=%s)", symbol, order_id
            )
            order.status = OrderStatus.REJECTED
            order.order_id = order_id
            return order_id

        # ISS-021 (parity): honor reduceOnly so paper matches live exchange
        # semantics. A reduceOnly SELL may only flatten an existing long (never
        # flip into a new short); a reduceOnly BUY may only flatten a short.
        # Without this, paper _update_position would flip the position while a
        # live OKX reduceOnly order is rejected at the exchange — paper showed a
        # phantom short that live never opened. Cap the fill to |held|; if there
        # is no position to reduce, reject (the exchange would).
        if order.params.get("reduceOnly"):
            held = self._positions.get(symbol)
            held_qty = held.quantity if held is not None else 0.0
            if abs(held_qty) < POSITION_EPSILON:
                logger.warning(
                    "Paper reduceOnly order REJECTED: no position to reduce for %s (order_id=%s)",
                    symbol,
                    order_id,
                )
                order.status = OrderStatus.REJECTED
                order.order_id = order_id
                return order_id
            if side == "buy" and held_qty < 0:
                quantity = min(quantity, abs(held_qty))
            elif side == "sell" and held_qty > 0:
                quantity = min(quantity, held_qty)
            # else: same-direction reduceOnly is a no-op-ish case (e.g. SELL on a
            # short); leave quantity unchanged — _update_position handles it.

        # Slippage: legacy path applies flat slip on last/mid; orderbook path
        # already used bid/ask as the touch — only optional extra_slip applies.
        if self._orderbook_fill_enabled and symbol in self._bbo:
            extra = self._orderbook_extra_slip
            if extra > 0:
                slip_mult = 1 + extra if side == "buy" else 1 - extra
                fill_price *= slip_mult
        else:
            slip_mult = 1 + self._slippage if side == "buy" else 1 - self._slippage
            fill_price *= slip_mult

        # Calculate fees
        notional = fill_price * quantity
        fee = notional * self._taker_fee

        # ISS-20260720-004 Wave 2: PaperGateway no longer maintains a cash book.
        # L4 PortfolioManager (the authoritative book) is updated once by
        # ExecutionEngine.submit (fee included), so fee is not double-counted and
        # there is no third cash ledger to drift. PaperGateway retains a local
        # _positions view only for the gateway contract (query_positions /
        # reduceOnly caps) — mirroring how OKXGateway exposes the exchange's
        # position view without owning the L4 book.

        # Update the gateway's local position view (reduceOnly caps + query_positions).
        self._update_position(
            symbol,
            quantity if side == "buy" else -quantity,
            fill_price,
            strategy_id=order.strategy_id,
        )
        self._prices[symbol] = fill_price

        logger.info(
            "Paper fill: %s %s %.6f @ %.2f (fee=%.2f)", side, symbol, quantity, fill_price, fee
        )

        order.order_id = order_id
        # M4-5.15: simulate partial fill for limit orders when configured.
        if self._partial_fill_ratio is not None and order.order_type == "limit":
            fill_qty = quantity * self._partial_fill_ratio
            order.status = OrderStatus.PARTIAL
            order.filled_quantity = fill_qty
            order.filled_price = fill_price
            order.fee = fill_qty * fill_price * self._taker_fee
            return order_id
        order.status = OrderStatus.FILLED
        order.filled_quantity = quantity
        order.filled_price = fill_price
        order.fee = fee
        return order_id

    async def cancel_order(self, order_id: str, symbol: str = "") -> bool:
        # ISS-042 (RP4): validate at every gateway entry, symmetric with
        # send_order — even though paper cancel is a no-op, keeping the choke
        # point on every method prevents a future regression if cancel grows
        # logic. Mirror okx_gateway.cancel_order.
        if symbol:
            validate_symbol(symbol)
        # Paper orders fill instantly — nothing to cancel
        logger.debug("Paper cancel: %s (orders fill instantly, nothing to cancel)", order_id)
        return True

    async def cancel_all_orders(self, symbol: str | None = None) -> list[bool]:
        # ISS-042 (RP4): symmetric validate_symbol on the cancel path.
        if symbol is not None:
            validate_symbol(symbol)
        return []

    async def query_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def query_open_orders(self, symbol: str) -> list[OpenOrder]:
        """Query open orders from paper exchange.

        ISS-20260720-004 (Reconciliation): Paper orders fill instantly on
        submission, so there are never any open orders in paper mode.
        Returns empty list — symmetric with OKXGateway.fetch_open_orders()
        which returns exchange-side open orders.

        When partial_fill_ratio is configured (M4-5.15), partially filled
        limit orders could theoretically remain open, but the current
        implementation does not track them as persistent open orders.
        """
        return []

    async def subscribe(self, channel: str, callback: Any = None) -> None:
        """Mock WebSocket subscription — pushes local book data periodically.

        For paper trading: simulates a WebSocket feed by emitting the current
        local position state to *callback* every second.  Works without
        ccxt.pro (paper mode has no real exchange connection).

        Supported channels: ``'ohlcv'``.  Any other channel is a silent no-op
        so callers can issue speculative subscribes without error handling.
        """
        if channel == "ohlcv" and callback is not None:
            self._ws_task = asyncio.create_task(self._mock_ohlcv_loop(callback))
        else:
            logger.debug("PaperGateway.subscribe('%s'): no-op (channel or callback)", channel)

    async def _mock_ohlcv_loop(self, callback: Any) -> None:
        """Push synthetic OHLCV bars derived from local position prices.

        Each tick emits one bar per tracked symbol using the last known price
        as all four OHLC fields — enough for downstream consumers that only
        read ``close`` (most indicators / signal generators) while making the
        bar structurally valid for any OHLCV-aware pipeline.
        """
        while True:
            await asyncio.sleep(1.0)
            ts = int(asyncio.get_event_loop().time() * 1000)
            for _symbol, pos in list(self._positions.items()):
                price = pos.current_price
                bar = [[ts, price, price, price, price, 0.0]]
                if inspect.iscoroutinefunction(callback):
                    await callback(bar)
                else:
                    callback(bar)

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update last known price for a symbol (called by data feed).

        Overrides the GatewayBase no-op (odyssey-improve ARCH-M2) so
        ExecutionEngine.update_market_price calls a declared method instead
        of duck-typing ``update_price`` past the interface.
        """
        self._prices[symbol] = price
        pos = self._positions.get(symbol)
        if pos is not None:
            # ISS-20260723-002: route through Position.with_current_price —
            # the unrealized-PnL formula now has a single owner
            # (common/models.py), shared with PortfolioManager.
            self._positions[symbol] = pos.with_current_price(price)

    def update_orderbook(
        self,
        symbol: str,
        bid: float,
        ask: float,
        *,
        mid_to_last: bool = True,
    ) -> None:
        """Push best bid/ask for optional orderbook fill (W16).

        No-op effect on fills unless ``orderbook_fill.enabled`` is true.
        Invalid/crossed books are ignored (keep previous BBO).
        """
        try:
            b = float(bid)
            a = float(ask)
        except (TypeError, ValueError):
            return
        if b <= 0 or a <= 0 or b > a:
            logger.debug(
                "PaperGateway.update_orderbook ignored invalid BBO %s bid=%s ask=%s",
                symbol,
                bid,
                ask,
            )
            return
        self._bbo[symbol] = (b, a)
        if mid_to_last:
            mid = (b + a) / 2.0
            self.update_market_price(symbol, mid)

    def _resolve_fill_price(
        self,
        symbol: str,
        side: str,
        *,
        order_price: float | None,
    ) -> float:
        """Pick reference fill price before slip (W16 orderbook opt-in)."""
        if self._orderbook_fill_enabled:
            bbo = self._bbo.get(symbol)
            if bbo is not None:
                bid, ask = bbo
                if side == "buy":
                    return float(ask)
                return float(bid)
        if order_price is not None and float(order_price) > 0:
            return float(order_price)
        return float(self._prices.get(symbol, 0.0) or 0.0)

    def _update_position(
        self, symbol: str, quantity: float, price: float, *, strategy_id: str = ""
    ) -> None:
        existing = self._positions.get(symbol)
        if existing is None:
            if abs(quantity) < POSITION_EPSILON:
                return
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=quantity,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                strategy_id=strategy_id,
            )
            return

        new_qty = existing.quantity + quantity
        if abs(new_qty) < POSITION_EPSILON:
            del self._positions[symbol]
            return

        # Update average entry price (when adding to position)
        if (quantity > 0 and existing.quantity > 0) or (quantity < 0 and existing.quantity < 0):
            total_cost = existing.entry_price * abs(existing.quantity) + price * abs(quantity)
            avg_price = total_cost / abs(new_qty)
        elif existing.quantity * new_qty < 0:
            # Position flipped direction — new leg starts at the fill price so
            # P&L is not inverted on the new short/long.
            avg_price = price
        else:
            avg_price = existing.entry_price

        self._positions[symbol] = Position(
            symbol=symbol,
            quantity=new_qty,
            entry_price=avg_price,
            current_price=price,
            unrealized_pnl=(price - avg_price) * new_qty,
            strategy_id=existing.strategy_id or strategy_id,
        )

    @property
    def is_connected(self) -> bool:
        return True
