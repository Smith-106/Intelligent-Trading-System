"""Thread safety tests for OrderManager (REL-H7).

These tests verify that the thread-safe implementation correctly handles
concurrent access from multiple strategy threads without race conditions.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from quantflow.common.models import OrderRequest, OrderSide, OrderStatus, OrderType
from quantflow.execution.order_manager import OrderManager


class TestOrderManagerThreadSafety:
    """Test suite for thread-safe order management."""

    def test_concurrent_order_tracking(self):
        """Multiple threads can safely track orders concurrently."""
        manager = OrderManager()
        errors = []

        def track_orders(thread_id, start_idx, count):
            try:
                for i in range(count):
                    idx = start_idx + i
                    request = OrderRequest(
                        symbol="BTC/USDT",
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=0.1,
                        price=0.0,
                        strategy_id=f"strategy-{thread_id}",
                    )
                    # Use unique result to avoid timestamp collision
                    from quantflow.common.models import OrderResult, OrderStatus

                    result = OrderResult(
                        order_id=f"order-{thread_id}-{idx}",
                        status=OrderStatus.SUBMITTED,
                    )
                    manager.track(request, result)
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e!s}")

        # Simulate 5 strategies each tracking 20 orders concurrently
        threads = []
        for t in range(5):
            thread = threading.Thread(target=track_orders, args=(t, t * 20, 20))
            threads.append(thread)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"
        assert manager.total_orders == 100, f"Expected 100 total orders, got {manager.total_orders}"

    def test_concurrent_updates(self):
        """Multiple threads can safely update orders concurrently."""
        manager = OrderManager()
        errors = []

        # First create some orders
        for _i in range(10):
            request = OrderRequest(
                symbol="BTC/USDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=0.5,
                price=50000.0,
                strategy_id="main",
            )
            manager.track(request)

        def update_orders(thread_id, order_ids):
            try:
                for oid in order_ids:
                    manager.update(
                        oid, OrderStatus.FILLED, filled_quantity=0.5, filled_price=50000.0
                    )
            except Exception as e:
                errors.append(f"Thread {thread_id}: {e!s}")

        # Distribute orders among 3 threads
        order_list = list(manager._orders.keys())
        chunks = [order_list[i::3] for i in range(3)]

        threads = []
        for t, chunk in enumerate(chunks):
            thread = threading.Thread(target=update_orders, args=(t, chunk))
            threads.append(thread)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Update errors: {errors}"
        assert manager.pending_count == 0, "All orders should be terminal"

    def test_atomic_cancel_with_race_condition_protection(self):
        """Atomic cancel prevents terminal state resurrection."""
        manager = OrderManager()

        # Create an order
        request = OrderRequest(
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1.0,
            price=0.0,
            strategy_id="test",
        )
        order = manager.track(request)
        order_id = order.order_id

        # Try concurrent cancellation attempts
        results = []

        def try_cancel():
            success, reason = manager.cancel_order(order_id)
            results.append((success, reason))

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(try_cancel) for _ in range(5)]
            for _f in as_completed(futures):
                pass  # Wait for all

        # Only first cancellation should succeed
        successes = sum(1 for s, _ in results if s)
        assert successes == 1, f"Expected exactly 1 successful cancel, got {successes}"

        # Verify final status is CANCELLED
        final_order = manager.get_order(order_id)
        assert final_order.status == OrderStatus.CANCELLED

    def test_atomic_context_manager_exception_safety(self):
        """Context manager releases lock even on exception."""
        manager = OrderManager()

        # Create an order with a known ID
        from quantflow.common.models import OrderResult, OrderStatus

        request = OrderRequest(
            symbol="SOL/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=10.0,
            price=100.0,
            strategy_id="test",
        )
        result = OrderResult(
            order_id="test-order-001",
            status=OrderStatus.SUBMITTED,
        )
        manager.track(request, result)

        # Normal operation within context
        with manager._atomic_order_operation("test-order-001") as order:
            assert order.symbol == "SOL/USDT"

        # Verify lock released successfully by doing another operation
        get_result = manager.get_order("test-order-001")
        assert get_result is not None

        # Verify non-existent order raises KeyError within context
        with pytest.raises(KeyError, match="not found"):
            with manager._atomic_order_operation("non-existent"):
                pass  # Should never reach here

    def test_concurrent_get_operations(self):
        """Read operations don't block or corrupt state during writes."""
        manager = OrderManager(timeout=1)  # Short timeout for faster tests

        # Track initial order
        request = OrderRequest(
            symbol="ADA/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100.0,
            price=0.0,
            strategy_id="read-test",
        )
        manager.track(request)

        errors = []
        read_count = [0]  # Use list for mutable closure

        def read_loop():
            try:
                for _ in range(100):
                    _ = manager.get_order("local-read-test")
                    _ = manager.get_open_orders()
                    _ = manager.get_orders_by_strategy("read-test")
                    read_count[0] += 1
            except Exception as e:
                errors.append(str(e))

        # Start readers and writers concurrently

        def writer():
            for i in range(10):
                req = OrderRequest(
                    symbol="ADA/USDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=float(i),
                    price=0.0,
                    strategy_id="writer",
                )
                manager.track(req)
                time.sleep(0.01)

        reader_thread = threading.Thread(target=read_loop)
        writer_thread = threading.Thread(target=writer)

        reader_thread.start()
        writer_thread.start()
        reader_thread.join()
        writer_thread.join()

        assert len(errors) == 0, f"Concurrent read/write errors: {errors}"
        assert read_count[0] >= 90, f"Expected many reads, only got {read_count[0]}"
