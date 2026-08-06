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
class SegmentInfo:
    """One train/val/test segment of the split layout.

    Positions are FRACTIONAL (0..1 within the row window) so the layout is
    explicit but concrete calendar times never leak (P2.1.2).
    """

    segment: str  # "train" | "val" | "test"
    n_bars: int
    start_frac: float
    end_frac: float


@dataclass(frozen=True)
class DatasetSchema:
    """Schema-only view of a dataset. No raw data, no time boundaries."""

    symbol: str
    row_count: int
    date_range: tuple[str, str]  # ISO date strings only (not timestamps)
    columns: list[ColumnSchema]
    #: Explicit train/val/test layout (P2.1.2). Empty when no split was
    #: requested — fractional positions, never absolute times.
    splits: tuple[SegmentInfo, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize for LLM consumption."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "row_count": self.row_count,
            "date_range": {"start": self.date_range[0], "end": self.date_range[1]},
            "columns": [
                {"name": c.name, "dtype": c.dtype, "non_null_count": c.non_null_count}
                for c in self.columns
            ],
        }
        if self.splits:
            payload["splits"] = [
                {
                    "segment": s.segment,
                    "n_bars": s.n_bars,
                    "start_frac": round(s.start_frac, 4),
                    "end_frac": round(s.end_frac, 4),
                }
                for s in self.splits
            ]
        return payload


class SchemaExposure:
    """Generate schema-only views of datasets for LLM consumption.

    This class provides a safe interface between raw market data and
    LLM agents, ensuring the LLM only sees metadata (column names, types,
    basic statistics) without accessing actual values or time boundaries.
    """

    @staticmethod
    def from_dataframe(
        df: pd.DataFrame,
        symbol: str,
        splits: tuple[float, float, float] | None = None,
    ) -> DatasetSchema:
        """Create a schema-only view from a DataFrame.

        Args:
            df: Source DataFrame (OHLCV or features)
            symbol: Trading symbol identifier
            splits: optional (train, val, test) row fractions summing to 1.0;
                when provided the schema carries the explicit segment layout
                (bar counts + fractional positions, never absolute times).
                Default None = no split metadata (backward compatible).

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
            splits=_split_layout(len(df), splits),
        )


def _split_layout(
    n_rows: int, splits: tuple[float, float, float] | None
) -> tuple[SegmentInfo, ...]:
    """Build the fractional segment layout for ``n_rows`` (P2.1.2).

    Each fraction is RELATIVE (its own span), so boundaries accumulate:
    train [0, n*0.7), val [n*0.7, n*0.85), test [n*0.85, n). Positions are
    fractional — the layout is explicit, concrete times never leak.
    """
    if splits is None:
        return ()
    if len(splits) != 3:
        raise ValueError(f"splits must be (train, val, test), got {splits!r}")
    if any(f <= 0.0 for f in splits):
        raise ValueError(f"split fractions must be positive, got {splits!r}")
    total = sum(splits)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"split fractions must sum to 1.0, got {splits!r} (sum {total})")

    segments: list[SegmentInfo] = []
    cursor = 0
    for idx, frac in enumerate(splits):
        span = round(n_rows * frac)
        end = min(cursor + span, n_rows)
        segments.append(
            SegmentInfo(
                segment=("train", "val", "test")[idx],
                n_bars=max(0, end - cursor),
                start_frac=(cursor / n_rows) if n_rows else 0.0,
                end_frac=(end / n_rows) if n_rows else 0.0,
            )
        )
        cursor = end
    if cursor < n_rows:  # rounding tail lands in the last segment
        last = segments[-1]
        segments[-1] = SegmentInfo(
            segment=last.segment,
            n_bars=last.n_bars + (n_rows - cursor),
            start_frac=last.start_frac,
            end_frac=1.0,
        )
    return tuple(segments)
