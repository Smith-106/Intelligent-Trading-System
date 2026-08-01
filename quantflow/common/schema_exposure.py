"""Schema-only data exposure for LLM-driven factor mining (ISS-20260722-003).

Provides a read-only schema interface that LLM agents (e.g., Qlib RD-Agent)
can query without accessing raw market data or time split boundaries.
This prevents future data leakage per the schema-only design principle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ColumnSchema:
    """Schema description for a single column."""

    name: str
    dtype: str
    non_null_count: int
    sample_values: list[Any]  # First 3 values only


@dataclass(frozen=True)
class DatasetSchema:
    """Schema-only view of a dataset. No raw data, no time boundaries."""

    symbol: str
    row_count: int
    date_range: tuple[str, str]  # ISO date strings only (not timestamps)
    columns: list[ColumnSchema]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for LLM consumption."""
        return {
            "symbol": self.symbol,
            "row_count": self.row_count,
            "date_range": {"start": self.date_range[0], "end": self.date_range[1]},
            "columns": [
                {"name": c.name, "dtype": c.dtype, "non_null_count": c.non_null_count}
                for c in self.columns
            ],
        }


class SchemaExposure:
    """Generate schema-only views of datasets for LLM consumption.

    This class provides a safe interface between raw market data and
    LLM agents, ensuring the LLM only sees metadata (column names, types,
    basic statistics) without accessing actual values or time boundaries.
    """

    @staticmethod
    def from_dataframe(df: pd.DataFrame, symbol: str) -> DatasetSchema:
        """Create a schema-only view from a DataFrame.

        Args:
            df: Source DataFrame (OHLCV or features)
            symbol: Trading symbol identifier

        Returns:
            DatasetSchema with metadata only — no raw data exposure
        """
        columns = []
        for col in df.columns:
            series = df[col]
            sample = series.head(3).tolist() if len(series) >= 3 else series.tolist()
            columns.append(
                ColumnSchema(
                    name=col,
                    dtype=str(series.dtype),
                    non_null_count=int(series.notna().sum()),
                    sample_values=sample,
                )
            )

        # Date range as ISO strings (not raw timestamps)
        if "datetime" in df.columns:
            dates = pd.to_datetime(df["datetime"])
            date_range = (dates.min().isoformat(), dates.max().isoformat())
        elif hasattr(df.index, "dtype") and df.index.dtype.kind == "M":  # 'M' for datetime64
            date_range = (df.index.min().isoformat(), df.index.max().isoformat())
        else:
            date_range = ("unknown", "unknown")

        return DatasetSchema(
            symbol=symbol,
            row_count=len(df),
            date_range=date_range,
            columns=columns,
        )
