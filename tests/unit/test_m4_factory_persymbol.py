"""Tests for strategy factory per-(strategy, symbol) instance creation (M4-2.1).

The factory creates isolated strategy clones for each symbol so that mutable
state (bars, EMA windows, position flags) does not cross-pollinate.  These
tests verify the single-symbol fast path (identity reuse), multi-symbol
cloning (distinct instances), state isolation, and params preservation.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quantflow.common.models import Bar
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.factory import create_all_per_symbol, create_per_symbol


class _StatefulStrategy(StrategyBase):
    """Local strategy subclass with mutable per-instance state.

    The default ``name`` is ``"s1"`` so that test 7 can verify the factory
    overwrites ``instance.name`` with the prototype's name even when the
    class default differs.
    """

    def __init__(
        self,
        name: str = "s1",
        params: dict[str, Any] | None = None,
        **_kw: Any,
    ) -> None:
        super().__init__(name=name, params=params)
        self._bars: list[str] = []

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar.symbol)

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        empty = pd.Series(False, index=df.index)
        return empty, empty


class TestCreatePerSymbol:
    def test_single_symbol_reuses_original_instance(self) -> None:
        """Single-symbol fast path: original instance reused (identity, not clone)."""
        strategy = _StatefulStrategy(name="proto", params={"fast": 10})
        result = create_per_symbol(strategy, ["BTC/USDT"])
        assert len(result) == 1
        key = ("proto", "BTC/USDT")
        assert key in result
        assert result[key] is strategy  # identity check, NOT a clone

    def test_multi_symbol_creates_distinct_instances(self) -> None:
        """Multi-symbol: each symbol gets a distinct clone (not identity to original or each other)."""
        strategy = _StatefulStrategy(name="proto", params={"fast": 10})
        result = create_per_symbol(strategy, ["BTC/USDT", "ETH/USDT"])
        assert len(result) == 2
        btc = result[("proto", "BTC/USDT")]
        eth = result[("proto", "ETH/USDT")]
        assert btc is not strategy  # not identity to original
        assert eth is not strategy
        assert btc is not eth  # distinct from each other

    def test_clone_name_equals_prototype_name(self) -> None:
        """Each clone's .name equals the prototype's name (not symbol-suffixed)."""
        strategy = _StatefulStrategy(name="proto", params={"fast": 10})
        result = create_per_symbol(strategy, ["BTC/USDT", "ETH/USDT"])
        for instance in result.values():
            assert instance.name == "proto"

    def test_state_isolation_between_clones(self) -> None:
        """Mutating one clone's mutable state does not affect siblings or the original."""
        strategy = _StatefulStrategy(name="proto", params={"fast": 10})
        result = create_per_symbol(strategy, ["BTC/USDT", "ETH/USDT"])
        clone_a = result[("proto", "BTC/USDT")]
        clone_b = result[("proto", "ETH/USDT")]
        ctx = StrategyContext()
        bar = Bar(
            symbol="BTC/USDT",
            timestamp=0,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
        )
        clone_a.on_bar(ctx, bar)
        assert clone_a._bars == ["BTC/USDT"]
        assert clone_b._bars == []  # sibling unaffected
        assert strategy._bars == []  # original unaffected

    def test_cloning_preserves_params(self) -> None:
        """Clones receive a shallow copy of the prototype's params dict."""
        strategy = _StatefulStrategy(name="proto", params={"fast": 10})
        result = create_per_symbol(strategy, ["BTC/USDT", "ETH/USDT"])
        clone_a = result[("proto", "BTC/USDT")]
        clone_b = result[("proto", "ETH/USDT")]
        assert clone_a.params == {"fast": 10}
        assert clone_b.params == {"fast": 10}
        # Shallow copy: top-level dict is a distinct object per clone
        assert clone_a.params is not clone_b.params
        assert clone_a.params is not strategy.params
        # Mutating one clone's params dict does not affect others
        clone_a.params["fast"] = 20
        assert clone_b.params["fast"] == 10
        assert strategy.params["fast"] == 10

    def test_create_all_per_symbol_merges(self) -> None:
        """create_all_per_symbol merges per-strategy results into one mapping."""
        s1 = _StatefulStrategy(name="alpha", params={"x": 1})
        s2 = _StatefulStrategy(name="beta", params={"y": 2})
        result = create_all_per_symbol([s1, s2], ["BTC/USDT", "ETH/USDT"])
        assert len(result) == 4
        expected_keys = {
            ("alpha", "BTC/USDT"),
            ("alpha", "ETH/USDT"),
            ("beta", "BTC/USDT"),
            ("beta", "ETH/USDT"),
        }
        assert set(result.keys()) == expected_keys
        # Each maps to the correct strategy name
        for (name, _symbol), instance in result.items():
            assert instance.name == name

    def test_clone_name_overrides_class_default(self) -> None:
        """Factory overwrites instance.name even when the class default differs."""
        # Class default name is "s1" (from __init__).
        default_instance = _StatefulStrategy(params={"fast": 10})
        assert default_instance.name == "s1"
        # Prototype uses a different name.
        strategy = _StatefulStrategy(name="custom_proto", params={"fast": 10})
        assert strategy.name == "custom_proto"
        result = create_per_symbol(strategy, ["BTC/USDT", "ETH/USDT"])
        for instance in result.values():
            assert instance.name == "custom_proto"
