"""Strategy factory — per-(strategy, symbol) instance creation (M4-2.1).

Multi-symbol mode requires each strategy to maintain independent state per
symbol (bars, EMA, position flags). A single strategy instance fed bars from
multiple symbols would corrupt its internal state (cross-symbol pollution).

This module provides the factory function that TradingSession uses to create
isolated strategy instances for each (strategy, symbol) pair.
"""

from __future__ import annotations

from quantflow.strategy.base import StrategyBase


def create_per_symbol(
    strategy: StrategyBase,
    symbols: list[str],
) -> dict[tuple[str, str], StrategyBase]:
    """Create isolated strategy instances for each symbol.

    For a single-symbol list, returns the original instance unchanged (zero
    overhead, preserves backward compatibility). For multiple symbols, clones
    the strategy via its class constructor with the same params.

    Args:
        strategy: The prototype strategy instance (provides class + params + name).
        symbols: List of symbols to create instances for.

    Returns:
        Mapping of (strategy_name, symbol) → strategy instance.
        For single-symbol, the original instance is reused (not cloned).

    Note:
        Cloning uses ``type(strategy)(params=strategy.params)`` which invokes
        the strategy's __init__ with the same parameter dict. Strategies that
        require additional constructor arguments beyond ``params`` must ensure
        their __init__ signature is compatible with this pattern.
    """
    name = strategy.name

    if len(symbols) == 1:
        # Single-symbol fast path: reuse the original instance (backward compat).
        return {(name, symbols[0]): strategy}

    instances: dict[tuple[str, str], StrategyBase] = {}
    for symbol in symbols:
        # Create a fresh instance with the same params for each symbol.
        # Each instance maintains independent _bars, _in_position, EMA state, etc.
        instance = type(strategy)(params=dict(strategy.params))
        # Preserve the strategy name (used for allocation, risk budgets, logging).
        # The (name, symbol) tuple key provides uniqueness — the name itself stays
        # human-readable without symbol suffix.
        instance.name = name
        instances[(name, symbol)] = instance

    return instances


def create_all_per_symbol(
    strategies: list[StrategyBase],
    symbols: list[str],
) -> dict[tuple[str, str], StrategyBase]:
    """Create per-symbol instances for a list of strategies.

    Convenience wrapper that calls create_per_symbol for each strategy and
    merges the results into a single mapping.

    Args:
        strategies: List of prototype strategy instances.
        symbols: List of symbols to create instances for.

    Returns:
        Combined mapping of (strategy_name, symbol) → strategy instance.
    """
    result: dict[tuple[str, str], StrategyBase] = {}
    for strategy in strategies:
        result.update(create_per_symbol(strategy, symbols))
    return result
