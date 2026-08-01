"""Phase 6 (M4 v0.2) tests for PaperGateway ``partial_fill_ratio`` path.

Covers the opt-in partial-fill simulation for limit orders introduced in
M4-5.15 (quantflow/execution/paper_gateway.py). Deterministic and fully
offline — no exchange, no network, no clocks.

Source contract confirmed by reading paper_gateway.py + common/models.py:

* ``PaperGateway(config: dict | None = None)`` — config keys:
  ``partial_fill_ratio`` (default None; clamped to [0.01, 0.99] when set),
  ``slippage`` (default 0.001, clamped [0, 0.5]), ``maker_fee`` (0.0008),
  ``taker_fee`` (0.001), ``initial_capital`` (1_000_000).
* ``async def send_order(self, order: Order) -> str`` — takes an ``Order``
  dataclass, returns the order_id (``"paper-<n>"``) and MUTATES the passed
  order's ``order_id`` / ``status`` / ``filled_quantity`` / ``filled_price``
  / ``fee`` in place.
* Partial path: if ``self._partial_fill_ratio is not None`` AND
  ``order.order_type == "limit"`` -> ``fill_qty = quantity * ratio``,
  ``status = PARTIAL``, ``fee = fill_qty * fill_price * taker_fee``.
* reduceOnly caps the fillable ``quantity`` to ``|held|`` (lines 93-110)
  BEFORE the partial ratio applies (line 144), so a capped partial fill is
  ``min(quantity, |position|) * ratio``, not ``|position|``.

Fee note: the source computes ``fee`` on the slippage-adjusted ``fill_price``
(``fill_price *= slip_mult`` then ``fee = fill_price * qty * taker_fee``).
To assert the documented ``fee == qty * price * taker_fee`` formula exactly
we set ``slippage = 0.0`` in every fee-asserting case so ``fill_price == price``.
``filled_quantity`` is slippage-independent, so the clamping cases use the
literal ``PaperGateway({"partial_fill_ratio": ...})`` construction.
"""

from __future__ import annotations

import pytest

from quantflow.common.models import Order, OrderSide, OrderStatus, Position
from quantflow.execution.paper_gateway import PaperGateway

# Default taker fee per the contract / source default.
TAKER_FEE = 0.001


def _make_order(
    *,
    order_type: str = "limit",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 2.0,
    price: float = 100.0,
    symbol: str = "BTCUSDT",
    reduce_only: bool = False,
) -> Order:
    """Build a minimal ``Order`` for ``PaperGateway.send_order``.

    ``order_id`` starts empty — ``send_order`` overwrites it with
    ``"paper-<n>"``. ``price`` is always set because the gateway falls back to
    an internal price map when the price is falsy; setting it keeps the test
    deterministic and offline. ``params`` carries CCXT's ``reduceOnly`` flag
    when requested (the gateway reads ``order.params.get("reduceOnly")``).
    """
    return Order(
        order_id="",
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        price=price,
        params={"reduceOnly": True} if reduce_only else {},
    )


@pytest.mark.asyncio
async def test_default_no_partial_ratio_limit_fills_completely() -> None:
    """Baseline preserved: with no ``partial_fill_ratio`` a limit order fills
    fully — status FILLED, filled_quantity == quantity, fee on full notional."""
    gw = PaperGateway({"slippage": 0.0})
    order = _make_order(order_type="limit", quantity=2.0, price=100.0)
    order_id = await gw.send_order(order)

    assert order_id == order.order_id
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == pytest.approx(2.0)
    assert order.fee == pytest.approx(2.0 * 100.0 * TAKER_FEE)


@pytest.mark.asyncio
async def test_partial_ratio_halves_limit_fill() -> None:
    """ratio=0.5 on a limit order -> PARTIAL, filled_quantity == quantity*0.5,
    fee computed on the partially-filled notional."""
    gw = PaperGateway({"partial_fill_ratio": 0.5, "slippage": 0.0})
    order = _make_order(order_type="limit", quantity=2.0, price=100.0)
    await gw.send_order(order)

    assert order.status == OrderStatus.PARTIAL
    assert order.filled_quantity == pytest.approx(2.0 * 0.5)
    assert order.fee == pytest.approx((2.0 * 0.5) * 100.0 * TAKER_FEE)


@pytest.mark.asyncio
async def test_partial_ratio_ignored_for_market_orders() -> None:
    """``partial_fill_ratio`` only affects LIMIT orders (source checks
    ``order.order_type == "limit"``). A MARKET order fills fully even when the
    ratio is set."""
    gw = PaperGateway({"partial_fill_ratio": 0.5, "slippage": 0.0})
    order = _make_order(order_type="market", quantity=2.0, price=100.0)
    await gw.send_order(order)

    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_partial_ratio_clamped_to_valid_range() -> None:
    """ratio is clamped to [0.01, 0.99]: 0.0 -> 0.01, 1.5 -> 0.99. The
    effective ratio is inferred from ``filled_quantity / quantity`` and is
    independent of slippage, so the literal contract construction is used."""
    quantity = 10.0

    gw_low = PaperGateway({"partial_fill_ratio": 0.0})
    order_low = _make_order(order_type="limit", quantity=quantity, price=100.0)
    await gw_low.send_order(order_low)
    assert order_low.status == OrderStatus.PARTIAL
    assert order_low.filled_quantity / quantity == pytest.approx(0.01)

    gw_high = PaperGateway({"partial_fill_ratio": 1.5})
    order_high = _make_order(order_type="limit", quantity=quantity, price=100.0)
    await gw_high.send_order(order_high)
    assert order_high.status == OrderStatus.PARTIAL
    assert order_high.filled_quantity / quantity == pytest.approx(0.99)


@pytest.mark.asyncio
async def test_negative_ratio_clamped_to_floor() -> None:
    """A negative ratio is clamped to the 0.01 floor (same effective value as
    0.0)."""
    quantity = 10.0
    gw = PaperGateway({"partial_fill_ratio": -0.5})
    order = _make_order(order_type="limit", quantity=quantity, price=100.0)
    await gw.send_order(order)

    assert order.status == OrderStatus.PARTIAL
    assert order.filled_quantity / quantity == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_partial_fill_fee_correctness() -> None:
    """Explicit numeric fee assertion under a partial fill: with quantity=4,
    ratio=0.5, price=50, taker_fee=0.001 -> fill_qty=2, fee=2*50*0.001=0.1."""
    gw = PaperGateway({"partial_fill_ratio": 0.5, "slippage": 0.0})
    order = _make_order(order_type="limit", quantity=4.0, price=50.0)
    await gw.send_order(order)

    fill_qty = 4.0 * 0.5
    assert order.filled_quantity == pytest.approx(fill_qty)
    assert order.fee == pytest.approx(fill_qty * 50.0 * TAKER_FEE)
    assert order.fee == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_reduce_only_cap_applied_before_partial_ratio() -> None:
    """reduceOnly caps the fillable ``quantity`` to ``|position|`` (lines
    93-110) BEFORE the partial ratio applies (line 144). So with quantity=10,
    a long position of 2, ratio=0.5: capped quantity = min(10, 2) = 2, partial
    fill = 2 * 0.5 = 1.0 (status PARTIAL) — NOT 10 * 0.5 = 5.0. The cap is
    honored and the status reflects the capped partial fill."""
    gw = PaperGateway({"partial_fill_ratio": 0.5, "slippage": 0.0})
    # Seed the gateway's local exchange view (what reduceOnly caps against)
    # directly to isolate the cap+ratio interaction from the seeding path.
    gw._positions["BTCUSDT"] = Position(
        symbol="BTCUSDT",
        quantity=2.0,
        entry_price=100.0,
        current_price=100.0,
    )
    order = _make_order(
        order_type="limit",
        side=OrderSide.SELL,
        quantity=10.0,
        price=100.0,
        reduce_only=True,
    )
    await gw.send_order(order)

    capped_qty = min(10.0, 2.0)
    assert order.status == OrderStatus.PARTIAL
    assert order.filled_quantity == pytest.approx(capped_qty * 0.5)
    assert order.fee == pytest.approx((capped_qty * 0.5) * 100.0 * TAKER_FEE)


@pytest.mark.asyncio
async def test_send_order_returns_nonempty_string_id() -> None:
    """``send_order`` returns a non-empty string order_id (``"paper-<n>"``)
    that is also written back onto the passed order."""
    gw = PaperGateway({"slippage": 0.0})
    order = _make_order(order_type="limit", quantity=1.0, price=100.0)
    order_id = await gw.send_order(order)

    assert isinstance(order_id, str)
    assert order_id  # non-empty
    assert order_id == order.order_id
    assert order_id.startswith("paper-")
