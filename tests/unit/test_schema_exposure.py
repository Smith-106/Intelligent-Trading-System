"""Tests for schema_exposure.py (ISS-20260722-003)."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.common.schema_exposure import SchemaExposure


@pytest.fixture
def sample_ohlcv_df() -> pd.DataFrame:
    """Minimal OHLCV DataFrame for schema tests."""
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=10, freq="1h"),
            "open": [100.0 + i for i in range(10)],
            "high": [101.0 + i for i in range(10)],
            "low": [99.0 + i for i in range(10)],
            "close": [100.5 + i for i in range(10)],
            "volume": [1000.0 + i * 100 for i in range(10)],
        }
    )


class TestSchemaExposure:
    """Verify SchemaExposure produces correct schema-only views."""

    def test_from_dataframe_basic(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """from_dataframe returns correct symbol, row_count, column count."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        assert schema.symbol == "BTC/USDT"
        assert schema.row_count == 10
        assert len(schema.columns) == 6  # datetime + OHLCV

    def test_column_schema_fields(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Each ColumnSchema has name, dtype, non_null_count, 3 sample values."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        close_col = next(c for c in schema.columns if c.name == "close")
        assert close_col.dtype == "float64"
        assert close_col.non_null_count == 10
        assert len(close_col.sample_values) == 3

    def test_date_range_from_datetime_column(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Date range extracted from 'datetime' column as ISO strings."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        assert schema.date_range[0].startswith("2024-01-01")
        assert schema.date_range[1].startswith("2024-01-01")

    def test_date_range_from_index(self) -> None:
        """Date range extracted from DatetimeIndex when no datetime column."""
        df = pd.DataFrame(
            {"close": [1.0, 2.0, 3.0]},
            index=pd.date_range("2025-06-01", periods=3, freq="1D"),
        )
        schema = SchemaExposure.from_dataframe(df, "ETH/USDT")
        # isoformat returns full datetime string; extract date portion
        assert "2025-06-01" in schema.date_range[0][:10]
        assert "2025-06-03" in schema.date_range[1][:10]

    def test_date_range_unknown(self) -> None:
        """No datetime info → date_range is ('unknown', 'unknown')."""
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        schema = SchemaExposure.from_dataframe(df, "X/USDT")
        assert schema.date_range == ("unknown", "unknown")

    def test_sample_values_limited_to_three(self) -> None:
        """Even with 100 rows, sample_values contains only 3 values."""
        df = pd.DataFrame({"close": list(range(100))})
        schema = SchemaExposure.from_dataframe(df, "TEST")
        col = schema.columns[0]
        assert len(col.sample_values) == 3

    def test_fewer_than_three_rows(self) -> None:
        """When DataFrame has <3 rows, sample_values has that many."""
        df = pd.DataFrame({"close": [42.0, 43.0]})
        schema = SchemaExposure.from_dataframe(df, "TEST")
        assert len(schema.columns[0].sample_values) == 2

    def test_to_dict_serialization(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """to_dict produces JSON-serializable structure."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        d = schema.to_dict()
        assert d["symbol"] == "BTC/USDT"
        assert d["row_count"] == 10
        assert "start" in d["date_range"]
        assert "end" in d["date_range"]
        assert len(d["columns"]) == 6
        # Column dicts have name, dtype, non_null_count (no sample_values)
        for col_d in d["columns"]:
            assert "name" in col_d
            assert "dtype" in col_d
            assert "non_null_count" in col_d

    def test_to_dict_excludes_sample_values(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """to_dict serialization does NOT include sample_values (no raw data leak)."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        d = schema.to_dict()
        for col_d in d["columns"]:
            assert "sample_values" not in col_d

    def test_raw_data_not_in_schema_beyond_samples(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Schema does not expose raw data values beyond the 3 sample values."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        close_col = next(c for c in schema.columns if c.name == "close")
        # Only first 3 values exposed; value at index 5 should not appear
        assert 105.5 not in close_col.sample_values  # index 5 value
        assert len(close_col.sample_values) == 3

    def test_frozen_dataclasses(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """ColumnSchema and DatasetSchema are frozen (immutable)."""
        schema = SchemaExposure.from_dataframe(sample_ohlcv_df, "BTC/USDT")
        with pytest.raises(AttributeError):
            schema.symbol = "CHANGED"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            schema.columns[0].name = "CHANGED"  # type: ignore[misc]

    def test_null_count_with_missing_values(self) -> None:
        """non_null_count correctly reflects NaN presence."""
        df = pd.DataFrame({"close": [1.0, None, 3.0, None, 5.0]})
        schema = SchemaExposure.from_dataframe(df, "TEST")
        assert schema.columns[0].non_null_count == 3


class TestRdAgentSchemaWiring:
    """P2.1 hand-off boundary: with a DatasetSchema the rdagent CLI receives
    the TRAIN slice only + a schema.json audit file; legacy (None) keeps the
    full frame. (ISS-20260722-003: discover_factors signature change.)"""

    @staticmethod
    def _ohlcv(n: int = 300) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": [1_780_000_000_000 + i * 3_600_000 for i in range(n)],
                "open": [100.0 + i for i in range(n)],
                "high": [102.0 + i for i in range(n)],
                "low": [98.0 + i for i in range(n)],
                "close": [101.0 + i for i in range(n)],
                "volume": [10.0] * n,
            }
        )

    def test_discover_factors_with_schema_writes_train_slice(self, monkeypatch) -> None:
        """CLI path with a DatasetSchema: CSV holds the train slice only and
        schema.json records what the LLM designs against."""
        import json
        import subprocess as sp
        from pathlib import Path
        from unittest.mock import Mock

        from quantflow.common.schema_exposure import SchemaExposure
        from quantflow.strategy.rd_agent import RDAgentRunner

        df = self._ohlcv()
        schema = SchemaExposure.from_dataframe(df, "BTC/USDT")
        fake_run = Mock(return_value=sp.CompletedProcess([], 0, stdout="", stderr=""))

        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent")))
        monkeypatch.setattr("quantflow.strategy.rd_agent.subprocess.run", fake_run)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        RDAgentRunner().discover_factors(df, schema=schema)
        assert fake_run.call_count == 1, "rdagent CLI was not invoked"

        workdir = Path("data/rdagent_work")
        data = pd.read_csv(workdir / "ohlcv_input.csv")
        train_n = round(len(df) * 0.7)
        assert len(data) == train_n, "CSV must hold the train slice only"
        # No val/test timestamp may appear in the CSV.
        assert int(data["timestamp"].max()) <= int(df["timestamp"].iloc[train_n - 1])

        audit = json.loads((workdir / "schema.json").read_text(encoding="utf-8"))
        assert audit["symbol"] == "BTC/USDT"
        assert audit["row_count"] == len(df)
        assert any(c["name"] == "close" for c in audit["columns"])

    def test_legacy_call_without_schema_keeps_full_frame(self, monkeypatch) -> None:
        """Backward compatibility: schema=None -> full df to the CLI."""
        import subprocess as sp
        from pathlib import Path
        from unittest.mock import Mock

        from quantflow.strategy.rd_agent import RDAgentRunner

        df = self._ohlcv()
        fake_run = Mock(return_value=sp.CompletedProcess([], 0, stdout="", stderr=""))

        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent")))
        monkeypatch.setattr("quantflow.strategy.rd_agent.subprocess.run", fake_run)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        RDAgentRunner().discover_factors(df)
        data = pd.read_csv(Path("data/rdagent_work/ohlcv_input.csv"))
        assert len(data) == len(df)


class TestSplitLayout:
    """P2.1.2: explicit train/val/test segment metadata — fractional layout,
    chronological and non-overlapping, never absolute times."""

    def test_splits_metadata_shape(self) -> None:
        df = pd.DataFrame(
            {"close": range(300)},
            index=pd.date_range("2024-01-01", periods=300, freq="1h"),
        )
        schema = SchemaExposure.from_dataframe(df, "BTC/USDT", splits=(0.7, 0.15, 0.15))
        assert [s.segment for s in schema.splits] == ["train", "val", "test"]
        assert sum(s.n_bars for s in schema.splits) == schema.row_count
        # Chronological, non-overlapping, positive spans.
        prev_end = 0.0
        for seg in schema.splits:
            assert seg.start_frac >= prev_end - 1e-9
            assert seg.end_frac > seg.start_frac
            prev_end = seg.end_frac
        # No absolute time may appear in the serialized layout.
        payload = schema.to_dict()
        assert "splits" in payload
        assert all("2024" not in str(s) for s in payload["splits"])

    def test_no_splits_when_not_requested(self) -> None:
        df = pd.DataFrame({"close": range(10)})
        schema = SchemaExposure.from_dataframe(df, "BTC/USDT")
        assert schema.splits == ()
        assert "splits" not in schema.to_dict()

    def test_invalid_splits_rejected(self) -> None:
        df = pd.DataFrame({"close": range(10)})
        with pytest.raises(ValueError):
            SchemaExposure.from_dataframe(df, "BTC/USDT", splits=(0.5, 0.5, 0.5))
        with pytest.raises(ValueError):
            SchemaExposure.from_dataframe(df, "BTC/USDT", splits=(0.9, 0.1, 0.1))

    def test_rdagent_handoff_uses_explicit_train_segment(self, monkeypatch) -> None:
        """CLI hand-off honors the explicit train n_bars from schema.splits
        (not the legacy TRAIN_FRACTION threshold)."""
        import json
        import subprocess as sp
        from pathlib import Path
        from unittest.mock import Mock

        from quantflow.strategy.rd_agent import RDAgentRunner

        df = pd.DataFrame(
            {
                "timestamp": [1_780_000_000_000 + i * 3_600_000 for i in range(200)],
                "close": [100.0 + i for i in range(200)],
                "volume": [10.0] * 200,
            }
        )
        schema = SchemaExposure.from_dataframe(df, "BTC/USDT", splits=(0.6, 0.2, 0.2))
        fake_run = Mock(return_value=sp.CompletedProcess([], 0, stdout="", stderr=""))
        monkeypatch.setattr(RDAgentRunner, "check_available", staticmethod(lambda: (True, "")))
        monkeypatch.setattr(RDAgentRunner, "cli_available", staticmethod(lambda: (True, "rdagent")))
        monkeypatch.setattr("quantflow.strategy.rd_agent.subprocess.run", fake_run)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        RDAgentRunner().discover_factors(df, schema=schema)
        data = pd.read_csv(Path("data/rdagent_work/ohlcv_input.csv"))
        train_n = next(s.n_bars for s in schema.splits if s.segment == "train")
        assert len(data) == train_n  # 0.6 x 200 = 120, not the 0.7 default
        # Audit file carries the explicit layout.
        audit = json.loads((Path("data/rdagent_work/schema.json")).read_text(encoding="utf-8"))
        assert [s["segment"] for s in audit["splits"]] == ["train", "val", "test"]
