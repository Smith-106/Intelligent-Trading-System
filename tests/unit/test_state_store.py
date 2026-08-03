"""Unit tests for StateStore checkpoint persistence (T-s1-03).

Key scenarios (plan test_plan):
- save/load round-trip
- corrupt JSON -> load returns None (never raises) + last_error set
- schema version mismatch -> None
- os.replace atomicity: no .tmp residue after save
- missing checkpoint -> None with last_error None (fresh start, not failure)
"""

from __future__ import annotations

import json

import pytest

from quantflow.execution.state_store import (
    CHECKPOINT_FILENAME,
    CURRENT_SCHEMA_VERSION,
    SessionSnapshot,
    StateStore,
)


@pytest.fixture
def store(tmp_path):
    return StateStore(str(tmp_path / "checkpoints"))


def _snapshot() -> SessionSnapshot:
    return SessionSnapshot(
        saved_at_ms=1_700_000_000_000,
        mode="paper",
        cash=95_000.0,
        positions=[
            {
                "symbol": "BTC/USDT",
                "quantity": 0.5,
                "entry_price": 50_000.0,
                "current_price": 51_000.0,
                "unrealized_pnl": 500.0,
                "strategy_id": "trend",
            }
        ],
        open_orders=[{"order_id": "o1", "symbol": "BTC/USDT", "quantity": 0.1}],
        equity=120_500.0,
    )


class TestRoundTrip:
    def test_save_load_round_trip(self, store: StateStore):
        snap = _snapshot()
        store.save_checkpoint(snap)
        loaded = store.load_checkpoint()
        assert loaded is not None
        assert loaded.cash == pytest.approx(95_000.0)
        assert loaded.mode == "paper"
        assert loaded.positions == snap.positions
        assert loaded.open_orders == snap.open_orders
        assert loaded.equity == pytest.approx(120_500.0)
        assert loaded.schema_version == CURRENT_SCHEMA_VERSION
        assert store.last_error is None

    def test_overwrite_replaces_previous(self, store: StateStore):
        store.save_checkpoint(_snapshot())
        second = _snapshot()
        second.cash = 42.0
        store.save_checkpoint(second)
        loaded = store.load_checkpoint()
        assert loaded is not None and loaded.cash == pytest.approx(42.0)


class TestFailClosedLoad:
    def test_missing_checkpoint_returns_none_without_error(self, store: StateStore):
        assert store.load_checkpoint() is None
        assert store.last_error is None  # fresh start, NOT a failure

    def test_corrupt_json_returns_none_and_sets_error(self, store: StateStore, tmp_path):
        store.save_checkpoint(_snapshot())
        path = tmp_path / "checkpoints" / CHECKPOINT_FILENAME
        path.write_text("{not valid json", encoding="utf-8")
        assert store.load_checkpoint() is None
        assert store.last_error is not None

    def test_schema_version_mismatch_rejected(self, store: StateStore, tmp_path):
        snap = _snapshot()
        store.save_checkpoint(snap)
        path = tmp_path / "checkpoints" / CHECKPOINT_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = 999
        path.write_text(json.dumps(data), encoding="utf-8")
        assert store.load_checkpoint() is None
        assert store.last_error is not None
        assert "schema version" in store.last_error

    def test_non_object_root_rejected(self, store: StateStore, tmp_path):
        store.save_checkpoint(_snapshot())
        path = tmp_path / "checkpoints" / CHECKPOINT_FILENAME
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert store.load_checkpoint() is None
        assert store.last_error is not None


class TestAtomicWrite:
    def test_no_tmp_residue_after_save(self, store: StateStore, tmp_path):
        store.save_checkpoint(_snapshot())
        checkpoint_dir = tmp_path / "checkpoints"
        assert not (checkpoint_dir / (CHECKPOINT_FILENAME + ".tmp")).exists()
        assert (checkpoint_dir / CHECKPOINT_FILENAME).exists()

    def test_clear_removes_checkpoint_idempotently(self, store: StateStore):
        store.save_checkpoint(_snapshot())
        store.clear()
        assert store.load_checkpoint() is None
        store.clear()  # second clear must not raise
