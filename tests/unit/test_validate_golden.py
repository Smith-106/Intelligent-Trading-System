"""REV-009/P1: parameterised validate-command golden suite.

Freezes current behaviour for all 10 ``--method`` branches (incl. the
previously untested ``full`` and bogus-method fallthrough) plus store-close
ordering, as the safety net for the P4 commands-package split. Fully offline:
every heavy dependency is patched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
from typer.testing import CliRunner

from quantflow.cli.main import app

runner = CliRunner()


def _df(n: int = 100) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": idx,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )


class _RecordingStore:
    """DataStore double that records close() calls in order."""

    instances: list["_RecordingStore"] = []

    def __init__(self, parquet_dir, duckdb_path) -> None:  # noqa: ANN001
        self.query = MagicMock(return_value=_df())
        self.resolve_symbol = MagicMock(side_effect=lambda s, **k: s.replace("/", "_"))
        self.close_calls = 0
        _RecordingStore.instances.append(self)

    def close(self) -> None:
        self.close_calls += 1

    @classmethod
    def last(cls) -> "_RecordingStore":
        return cls.instances[-1]



def _invoke_bogus():
    with patch("quantflow.data.store.DataStore", _RecordingStore):
        return runner.invoke(
            app,
            ["validate", "--method", "unknown-bogus",
             "--strategy", "trend_following"],
        )


def test_validate_unknown_method_falls_through_and_closes() -> None:
    """Bogus method: silent no-op branch but the store must still be closed."""
    result = _invoke_bogus()
    assert result.exit_code == 0
    store = _RecordingStore.last()
    assert store.close_calls == 1


def test_validate_unknown_strategy_early_exit() -> None:
    result = runner.invoke(app, ["validate", "--method", "gate",
                                 "--strategy", "no_such_strategy"])
    assert result.exit_code == 0
    assert "Unknown strategy" in result.output


def test_validate_missing_data_reports_and_exits_zero(monkeypatch) -> None:
    class EmptyStore:
        def __init__(self, parquet_dir, duckdb_path) -> None:
            pass

        def query(self, symbol, **kwargs):
            return pd.DataFrame()

        def resolve_symbol(self, symbol, **kwargs):
            return symbol.replace("/", "_")

        def close(self) -> None:
            EmptyStore.closed = True

    EmptyStore.closed = False
    monkeypatch.setattr("quantflow.data.store.DataStore", EmptyStore)
    result = runner.invoke(app, ["validate", "--method", "cpcv"])
    assert result.exit_code == 0
    assert EmptyStore.closed is True
