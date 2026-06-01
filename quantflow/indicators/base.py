"""Factor base and registry for extensible indicator system."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import pandas as pd

logger = logging.getLogger(__name__)


class FactorBase(ABC):
    """Abstract base class for all indicator factors.

    Subclass and implement compute() to create custom factors.
    Register with FactorRegistry for automatic discovery.
    """

    name: str = ""
    dependencies: ClassVar[list[str]] = []

    @abstractmethod
    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute factor values from a DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with computed indicators.
        **params : Any
            Factor-specific parameters.

        Returns
        -------
        pd.Series
            Computed factor values, aligned to df index.
        """
        ...


class FactorRegistry:
    """Registry for factor discovery and lookup."""

    def __init__(self) -> None:
        self._factors: dict[str, type[FactorBase]] = {}

    def register(self, factor_cls: type[FactorBase]) -> None:
        """Register a factor class."""
        name = factor_cls.name or factor_cls.__name__
        self._factors[name] = factor_cls
        logger.debug("Registered factor: %s", name)

    def get(self, name: str) -> type[FactorBase] | None:
        """Look up a factor by name."""
        return self._factors.get(name)

    def list_factors(self) -> list[str]:
        """Return all registered factor names."""
        return sorted(self._factors.keys())

    def compute(self, name: str, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute a single factor by name."""
        cls = self.get(name)
        if cls is None:
            raise KeyError(f"Factor not registered: {name}")
        return cls().compute(df, **params)


# Global singleton registry
registry = FactorRegistry()
