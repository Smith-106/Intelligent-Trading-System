"""Drift-guard contract between the real DataStore and the test-suite's
shared store doubles.

History (REV-024 / hy3 x2): 13 test sites monkeypatched DataStore with
ad-hoc stubs that each implemented only a fragment of the public interface.
When the real store gained a method (``resolve_symbol``), a subset of those
stubs broke at runtime with ``AttributeError`` / ``TypeError`` instead of
failing at collection time.

This module pins the contract as a ``runtime_checkable`` Protocol derived
from the real store's public signatures, then asserts that every registered
store double (the shared ``FakeDataStore`` plus the concrete stub classes
that remain in other test modules) exposes the full interface.  Missing a
method therefore fails at *collection* time, not mid-run.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd
import pytest

from tests.unit.conftest import FakeDataStore

# Pinned copy of the real store's public method surface (kept independent of
# dir()) so the guard still fires when a stub omits a method.
REAL_PUBLIC_METHODS: tuple[str, ...] = (
    "query",
    "save",
    "save_funding_rates",
    "save_open_interest",
    "query_funding_rates",
    "query_open_interest",
    "get_last_meta_timestamp",
    "list_symbols",
    "resolve_symbol",
    "symbol_summary",
    "get_date_range",
    "get_last_timestamp",
    "group_cols",
    "close",
)


@runtime_checkable
class DataStoreProtocol(Protocol):
    """Public read/write surface of :class:`quantflow.data.store.DataStore`.

    A runtime-checkable Protocol lets ``isinstance``/``issubclass`` verify
    method *presence* eagerly, so an incomplete stub fails at collection.
    """

    def query(
        self,
        symbol: str,
        start: int | None = ...,
        end: int | None = ...,
        timeframe: str | None = ...,
        columns: list[str] | tuple[str, ...] | None = ...,
    ) -> pd.DataFrame: ...

    def save(self, df: pd.DataFrame, symbol: str) -> None: ...

    def save_funding_rates(self, df: pd.DataFrame, symbol: str) -> None: ...

    def save_open_interest(self, df: pd.DataFrame, symbol: str) -> None: ...

    def query_funding_rates(
        self,
        symbol: str,
        start: int | None = ...,
        end: int | None = ...,
    ) -> pd.DataFrame: ...

    def query_open_interest(
        self,
        symbol: str,
        start: int | None = ...,
        end: int | None = ...,
    ) -> pd.DataFrame: ...

    def get_last_meta_timestamp(self, symbol: str, data_type: str) -> int | None: ...

    def list_symbols(self) -> list[str]: ...

    def resolve_symbol(
        self,
        symbol: str,
        *,
        priority: tuple[str, ...] = ...,
    ) -> str: ...

    def symbol_summary(self, symbol: str) -> dict | None: ...

    def get_date_range(self, symbol: str) -> tuple[int, int] | None: ...

    def get_last_timestamp(self, symbol: str, timeframe: str) -> int | None: ...

    @staticmethod
    def group_cols(df: pd.DataFrame) -> list[str]: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Registry of every store double used across the suite.
#
# Keep this list in sync when adding/removing a DataStore stub.  The shared
# FakeDataStore is always covered; add any concrete stub class that other test
# modules still define so it is canonically guarded too.
# ---------------------------------------------------------------------------
DATASTORE_STUB_CLASSES: list[type] = [FakeDataStore]


def _missing_members(stub_cls: type) -> tuple[str, ...]:
    """Names of protocol methods absent on ``stub_cls`` (not callable)."""
    missing = []
    for method in REAL_PUBLIC_METHODS:
        attr = getattr(stub_cls, method, None)
        if not callable(attr):
            missing.append(method)
    return tuple(missing)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_protocol_covers_every_real_store_method() -> None:
    """The Protocol must not lag behind the real DataStore public surface.

    If someone adds a public method to the real store, this test fails until
    the Protocol (and therefore the shared FakeDataStore) is updated too.
    """
    from quantflow.data.store import DataStore

    real_public = [
        name
        for name in dir(DataStore)
        if not name.startswith("_") and callable(getattr(DataStore, name))
    ]
    expected = set(REAL_PUBLIC_METHODS)
    unexpected = [m for m in real_public if m not in expected]
    # Allow private helpers / dunders that start with '_' already filtered.
    assert not unexpected, (
        f"DataStore gained new public method(s) {unexpected!r} not mirrored in "
        f"DataStoreProtocol / FakeDataStore / REAL_PUBLIC_METHODS."
    )


@pytest.mark.parametrize(
    "stub_cls",
    DATASTORE_STUB_CLASSES,
    ids=lambda cls: f"{cls.__module__}.{cls.__name__}",
)
def test_stub_satisfies_full_datastore_interface(stub_cls: type) -> None:
    """Every registered stub exposes the complete DataStore interface.

    Failures surface at collection time (issubclass against a runtime_checkable
    Protocol is eager) instead of an AttributeError/TypeError mid-test.
    """
    missing = _missing_members(stub_cls)
    assert not missing, (
        f"{stub_cls.__module__}.{stub_cls.__name__} missing DataStore methods "
        f"{missing!r} -- either implement them or migrate the site to the "
        f"shared FakeDataStore."
    )
    assert issubclass(stub_cls, DataStoreProtocol)


def test_shared_fakestore_serves_configurable_behaviour() -> None:
    """Smoke-test the shared double's three configuration modes."""
    empty = FakeDataStore()
    assert empty.query("BTC/USDT").empty
    assert empty.closed is False
    empty.close()
    assert empty.closed is True

    frames = FakeDataStore(query=pd.DataFrame({"open": [1.0], "close": [2.0]}))
    out = frames.query("BTC/USDT")
    assert list(out.columns) == ["open", "close"]

    class StoreBoomError(Exception):
        pass

    raise_store = FakeDataStore(query_raise=StoreBoomError)
    with pytest.raises(StoreBoomError):
        raise_store.query("X")
