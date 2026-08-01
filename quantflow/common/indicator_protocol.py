"""Indicator computer Protocol — L1 (data/) seam for L2 (indicators/) access (ISS-002).

The data/ layer (L1) must not directly import from indicators/ (L2) — doing so
creates an upward layer violation (L1→L2). FeatureStore needs indicator
computation but should depend on an *interface*, not a concrete L2 class.

This module defines :class:`IndicatorComputer` (the Protocol contract that L2
implementations satisfy) and :class:`NullIndicatorComputer` (a fail-fast
sentinel that raises if compute_all is called without injection).

The real implementation lives in ``quantflow/indicators/engine.py``
(IndicatorEngine) and is injected by the caller — FeatureStore never imports
it directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class IndicatorComputer(Protocol):
    """Contract for indicator computation — decouples data/ from indicators/.

    Implementations MUST be safe to call with any OHLCV DataFrame. The
    returned DataFrame MUST contain all original columns plus computed
    indicator columns.
    """

    def compute_all(
        self, df: pd.DataFrame, indicator_names: list[str] | None = None
    ) -> pd.DataFrame:
        """Compute technical indicators on price data.

        Args:
            df: Price DataFrame with OHLCV columns.
            indicator_names: Optional subset of indicators to compute.
                If None, compute all available indicators.

        Returns:
            DataFrame with original columns + computed indicator columns.
        """
        ...


class NullIndicatorComputer:
    """Fail-fast sentinel — raises ValueError if compute_all is called.

    Used as the default when no IndicatorComputer is injected into
    FeatureStore. Forces the caller to explicitly provide a valid
    implementation before calling compute_features().
    """

    def compute_all(
        self, df: pd.DataFrame, indicator_names: list[str] | None = None
    ) -> pd.DataFrame:
        raise ValueError(
            "No IndicatorComputer injected into FeatureStore. "
            "Provide an IndicatorComputer instance via the constructor "
            "(e.g. IndicatorEngine from quantflow.indicators.engine)."
        )
