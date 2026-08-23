"""CLI entry point for QuantFlow."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

import typer
from rich.console import Console
from rich.table import Table

from quantflow import __version__
from quantflow.common.config import AppConfig, load_config, resolve_config_path
from quantflow.common.redaction import redact_secrets
from quantflow.monitoring.logger import setup_logging

setup_logging()

if TYPE_CHECKING:
    import pandas as pd

    from quantflow.strategy.base import StrategyBase

StrategyFactory: TypeAlias = Callable[[dict[str, Any] | None], "StrategyBase"]
ParamSpace: TypeAlias = dict[str, tuple[Any, ...]]
ResultDict: TypeAlias = dict[str, Any]


def _get_strategy_factories() -> dict[str, StrategyFactory]:
    # PERF(P1/A-2): imported lazily — the catalog chain pulls pandas into the
    # CLI cold path, which download/status/version/--help never need.
    from quantflow.strategy.catalog import get_strategy_factories

    return get_strategy_factories()


def _get_strategy_specs() -> dict[str, tuple[StrategyFactory, ParamSpace]]:
    from quantflow.strategy.catalog import get_strategy_specs

    return get_strategy_specs()


def _date_to_ms(date_str: str) -> int:
    """Convert a YYYY-MM-DD date string to UTC millisecond timestamp.

    DEF-REV011-F: malformed dates become a clean usage error instead of a raw
    ValueError traceback (validate called this outside its try block).
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as e:
        raise typer.BadParameter(
            f"日期格式须为 YYYY-MM-DD: {date_str!r}"
        ) from e
    return int(dt.timestamp() * 1000)


app = typer.Typer(
    name="quantflow",
    help="Personal Crypto quantitative trading system\n\nCommands: download → research → optimize → validate → run → status",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _make_console() -> Console:
    """Build a Console that does not crash on Windows GBK terminals.

    Legacy Windows consoles often use GBK/cp936, which cannot encode Unicode
    success/failure glyphs (U+2713/U+2717). Prefer UTF-8 stdio when the runtime
    allows reconfigure; always set ``legacy_windows=False`` so Rich avoids the
    Win32 legacy path that raised UnicodeEncodeError during download. Status
    markers themselves are ASCII ``OK`` / ``ERR`` as a second defense.
    """
    import contextlib
    import sys

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            # Stream may be closed, detached, or not reconfigurable (pytest capture).
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")
    return Console(legacy_windows=False, soft_wrap=True)


console = _make_console()
DEFAULT_CONFIG_PATH = "quantflow/config/default.yaml"


def _load(config_path: str) -> AppConfig:
    return load_config(config_path)


def _load_gateway_config_from_env(mode: str, sandbox: bool) -> dict[str, str | bool]:
    """Load gateway credentials from environment for sandbox/live modes."""
    gateway_config: dict[str, str | bool] = {"sandbox": sandbox}
    if mode == "paper":
        return gateway_config

    required_vars = {
        "OKX_API_KEY": "api_key",
        "OKX_SECRET": "secret",
        "OKX_PASSPHRASE": "passphrase",
    }
    missing = [name for name in required_vars if not os.getenv(name)]
    if missing:
        missing_text = ", ".join(missing)
        raise typer.BadParameter(
            f"Missing required environment variables for {mode} mode: {missing_text}"
        )

    for env_name, config_key in required_vars.items():
        gateway_config[config_key] = os.environ[env_name]
    return gateway_config


@app.command()
def download(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (single)"),
    symbols: str = typer.Option(
        "",
        help="Comma-separated multi-symbol, e.g. BTC/USDT,ETH/USDT,SOL/USDT (overrides --symbol)",
    ),
    timeframe: str = typer.Option("1d", help="K-line timeframe"),
    start: str = typer.Option("2024-01-01", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option("2025-01-01", help="End date (YYYY-MM-DD)"),
    okx_suffix: bool = typer.Option(True, help="Append -OKX suffix for source isolation"),
    concurrency: int = typer.Option(
        1,
        help="Max in-flight symbol downloads (keep 1 until verify_okx_throttler.py passes for N)",
        min=1,
        max=8,
    ),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Download historical data from OKX (single or batch symbol).

    Examples:
        quantflow download --symbol BTC/USDT --start 2024-01-01
        quantflow download --symbol ETH/USDT --timeframe 4h --start 2023-06-01
        quantflow download --symbols BTC/USDT,ETH/USDT,SOL/USDT --start 2024-01-01
    """
    from quantflow.data.cleaner import clean_ohlcv
    from quantflow.data.fetcher import DataFetcher
    from quantflow.data.store import DataStore

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] or [symbol]

    cfg = _load(config)

    async def _run() -> None:
        fetcher = DataFetcher(cfg.data)
        store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
        failed: list[str] = []
        # C-2 (PERF): >1 only after verify_okx_throttler.py --concurrency N
        # proves zero 429s; default keeps the serial M4-1.2 behaviour.
        sem = asyncio.Semaphore(max(1, concurrency))

        try:
            with console.status("[bold blue]Connecting to OKX..."):
                await fetcher.connect()
            console.print("[green]OK[/] Connected to OKX")

            # M4-1.2: single shared instance. The ccxt rate limiter stays
            # authoritative; --concurrency>1 only bounds how many symbol
            # pagination chains are in flight (each still throttled), and the
            # default of 1 preserves the historical serial behaviour exactly.
            async def _download_one(sym: str) -> None:
                try:
                    async with sem:
                        with console.status(
                            f"[bold blue]Downloading {sym} {timeframe} ({start} → {end})..."
                        ):
                            df = await fetcher.fetch_ohlcv(sym, timeframe, start, end)
                    if df.empty:
                        console.print(f"[yellow]SKIP[/] {sym}: no data (check symbol/date)")
                        # SKIP is not a failure: empty history is a legitimate
                        # outcome (symbol predates range). Only ERR sets the
                        # P5-F5 exit-code flag.
                        return
                    console.print(f"[dim]Raw data: {len(df)} bars for {sym}[/]")
                    with console.status("[bold blue]Cleaning data..."):
                        df = clean_ohlcv(df)
                    with console.status("[bold blue]Saving to Parquet..."):
                        store_symbol = f"{sym}-OKX" if okx_suffix else sym
                        store.save(df, store_symbol)
                    date_range = store.get_date_range(store_symbol)
                    console.print(
                        f"[green]OK[/] Saved [bold]{len(df)}[/] bars for [bold]{store_symbol}[/] ({timeframe})"
                    )
                    if date_range:
                        from datetime import datetime

                        s = datetime.fromtimestamp(date_range[0] / 1000).strftime("%Y-%m-%d")
                        e = datetime.fromtimestamp(date_range[1] / 1000).strftime("%Y-%m-%d")
                        console.print(f"  Range: {s} → {e}")
                except Exception as e:
                    # odyssey-review RP2 (ISS-037): scrub OKX secrets before print.
                    console.print(f"[red]ERR[/] {sym}: {redact_secrets(str(e))}")
                    failed.append(sym)

            if concurrency == 1:
                for sym in symbol_list:
                    await _download_one(sym)
            else:
                # save-on-complete inside _download_one keeps memory bounded;
                # distinct symbols write distinct partitions, and cross-process
                # same-partition races are serialised by the P2 FileLock.
                await asyncio.gather(*[_download_one(s) for s in symbol_list])
        except Exception as e:
            console.print(f"[red]ERR Error: {redact_secrets(str(e))}[/]")
            # P5-F5: a connect-level failure fails the whole batch — count
            # every requested symbol so the exit-code guard below fires.
            if not failed:
                failed.extend(symbol_list)
            console.print("  Check your internet connection and symbol name.")
        finally:
            await fetcher.disconnect()
            store.close()

        if failed:
            console.print(
                f"[yellow]WARNING:[/] {len(failed)}/{len(symbol_list)} symbols failed: {', '.join(failed)}"
            )
            # P5-F5 fix: a partially-failed batch must not report success to
            # automation — exit 1 so shell retry wrappers / CI can react.
            raise typer.Exit(1)

    asyncio.run(_run())


# T-s2-03: OKX funding-rate-history serves only ~3 months (analyze C2
# locked). Larger --days windows are truncated to this max with a WARNING —
# the shortfall is covered by incremental accumulation over time (DEV-1).
FUNDING_HISTORY_MAX_DAYS = 90
_OI_HISTORY_PERIODS = {"1H", "1D"}




def _run_meta_backfill(
    *,
    fetcher: Any,
    store: Any,
    connect_status: str,
    backfill_status: str,
    since_ms: int,
    fetch: Callable[[int], Awaitable[Any]],
    save: Callable[[Any], None],
    empty_msg: str,
    ok_msg: str,
    last_label: str,
    meta_kind: str,
    store_symbol: str,
) -> None:
    """Shared body for the four meta-backfill commands (funding/OI x OKX/Bybit).

    IMP-REV014-B: these commands previously repeated the same
    connect → fetch → empty-check → save → last-timestamp print → cleanup
    skeleton; only labels and callables differed. ``ok_msg`` may contain a
    ``{rows}`` placeholder filled with the fetched row count.
    """

    async def _run() -> None:
        try:
            with console.status(connect_status):
                await fetcher.connect()
            with console.status(backfill_status):
                df = await fetch(since_ms)
            if df.empty:
                console.print(f"[red]ERR {empty_msg}[/]")
                return
            save(df)
            last_ts = store.get_last_meta_timestamp(store_symbol, meta_kind)
            console.print("[green]OK[/] " + ok_msg.format(rows=len(df)))
            if last_ts is not None:
                last_date = datetime.fromtimestamp(last_ts / 1000, UTC).strftime("%Y-%m-%d")
                console.print(f"  {last_label}: {last_date}")
        except Exception as e:
            console.print(f"[red]ERR Error: {redact_secrets(str(e))}[/]")
            raise typer.Exit(code=1) from e
        finally:
            await fetcher.disconnect()
            store.close()

    asyncio.run(_run())



@app.command()
def download_funding(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (OKX swap)"),
    days: int = typer.Option(90, min=1, help="Backfill window in days (OKX max ~90)"),
    okx_suffix: bool = typer.Option(True, help="Append -OKX suffix for source isolation"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Backfill funding-rate history from OKX (limit=400 pagination).

    Examples:
        quantflow download-funding --symbol BTC/USDT --days 90
    """
    from quantflow.data.market_meta_fetcher import MarketMetaFetcher
    from quantflow.data.store import DataStore

    cfg = _load(config)
    store_symbol = f"{symbol}-OKX" if okx_suffix else symbol
    effective_days = days
    if days > FUNDING_HISTORY_MAX_DAYS:
        console.print(
            f"[yellow]WARNING:[/] OKX funding-rate-history serves a 3-month window only — "
            f"truncating {days}d request to {FUNDING_HISTORY_MAX_DAYS}d "
            "(incremental accumulation covers the rest over time)."
        )
        effective_days = FUNDING_HISTORY_MAX_DAYS

    fetcher = MarketMetaFetcher(cfg.data)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    since_ms = int(time.time() * 1000) - effective_days * 86_400_000
    _run_meta_backfill(
        fetcher=fetcher,
        store=store,
        connect_status="[bold blue]Connecting to OKX (meta endpoints)...",
        backfill_status=(
            f"[bold blue]Backfilling funding history for {symbol} ({effective_days}d)..."
        ),
        since_ms=since_ms,
        fetch=lambda since: fetcher.fetch_funding_rate_history(symbol, since),
        save=lambda df: store.save_funding_rates(df, store_symbol),
        empty_msg="No funding data fetched. Check the symbol.",
        ok_msg=f"Saved [bold]{{rows}}[/] funding rows for [bold]{store_symbol}[/]",
        last_label="Last funding time",
        meta_kind="funding_rate",
        store_symbol=store_symbol,
    )


@app.command()
def download_oi(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (OKX swap)"),
    days: int = typer.Option(180, min=1, help="Backfill window in days"),
    period: str = typer.Option("1H", help="OI granularity: 1H or 1D"),
    okx_suffix: bool = typer.Option(True, help="Append -OKX suffix for source isolation"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Backfill open-interest history from OKX (REST, limit=100 pagination).

    Examples:
        quantflow download-oi --symbol BTC/USDT --days 180 --period 1H
    """
    from quantflow.data.market_meta_fetcher import MarketMetaFetcher
    from quantflow.data.store import DataStore

    if period not in _OI_HISTORY_PERIODS:
        raise typer.BadParameter(f"period must be one of {sorted(_OI_HISTORY_PERIODS)}")

    cfg = _load(config)
    store_symbol = f"{symbol}-OKX" if okx_suffix else symbol

    fetcher = MarketMetaFetcher(cfg.data)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    since_ms = int(time.time() * 1000) - days * 86_400_000
    _run_meta_backfill(
        fetcher=fetcher,
        store=store,
        connect_status="[bold blue]Connecting to OKX (meta endpoints)...",
        backfill_status=f"[bold blue]Backfilling OI history for {symbol} ({days}d, {period})...",
        since_ms=since_ms,
        fetch=lambda since: fetcher.fetch_open_interest_history(
            symbol, period=period, since_ms=since
        ),
        save=lambda df: store.save_open_interest(df, store_symbol),
        empty_msg="No OI data fetched. Check the symbol.",
        ok_msg=(
            f"Saved [bold]{{rows}}[/] OI rows for [bold]{store_symbol}[/] ({period})"
        ),
        last_label="Last OI timestamp",
        meta_kind="open_interest",
        store_symbol=store_symbol,
    )


@app.command()
def download_binance(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (e.g. BTC/USDT)"),
    timeframe: str = typer.Option("1d", help="K-line timeframe (1m/5m/1h/4h/1d/...)"),
    start: str = typer.Option("2024-01", help="Start month (YYYY-MM)"),
    end: str = typer.Option("2025-01", help="End month (YYYY-MM)"),
    market: str = typer.Option("spot", help="Binance market: spot or futures"),
    binance_suffix: bool = typer.Option(True, help="Append -BINANCE suffix for source isolation"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Download historical klines from the Binance public archive (data.binance.vision).

    Free, no-auth, no-rate-limit monthly CSV archives. Ingested through the
    shared clean_ohlcv → DataStore.save pipeline (identical to OKX data).
    Stored with a ``-BINANCE`` suffix (e.g. ``BTC/USDT-BINANCE``) for exchange
    isolation — the symbol validator rejects ``.`` but allows ``-``.

    Examples:
        quantflow download-binance --symbol BTC/USDT --timeframe 1d --start 2019-01 --end 2026-08
        quantflow download-binance --symbol ETH/USDT --timeframe 4h --start 2021-01 --end 2024-01
        quantflow download-binance --symbol BTC/USDT --market futures --timeframe 1d --start 2020-01
    """
    from quantflow.data.binance_fetcher import BinanceArchiveFetcher, download_binance_to_store

    if market not in ("spot", "futures"):
        raise typer.BadParameter("market must be 'spot' or 'futures'")

    cfg = _load(config)
    fetcher = BinanceArchiveFetcher()
    from quantflow.data.store import store_scope

    store_symbol = f"{symbol}-BINANCE" if binance_suffix else symbol
    with store_scope(cfg.data.parquet_dir, cfg.data.duckdb_path) as store:
        try:
            with console.status(
                f"[bold blue]Downloading {symbol} {timeframe} ({start} → {end}) from Binance {market} archive..."
            ):
                df = download_binance_to_store(
                    fetcher,
                    store,
                    symbol,
                    timeframe,
                    start,
                    end,
                    market=market,
                    exchange_suffix=binance_suffix,
                )
            if df.empty:
                console.print(
                    "[red]ERR No data fetched. Check the symbol, timeframe, and date range.[/]"
                )
                console.print(
                    "  Hint: a symbol listed after the requested window returns nothing "
                    "(e.g. a 2021 token has no 2019 archive)."
                )
                return
            console.print(f"[dim]Raw data: {len(df)} bars[/]")
            date_range = store.get_date_range(store_symbol)
            console.print(
                f"[green]OK[/] Saved [bold]{len(df)}[/] bars for [bold]{store_symbol}[/] ({timeframe})"
            )
            if date_range:
                s = datetime.fromtimestamp(date_range[0] / 1000).strftime("%Y-%m-%d")
                e = datetime.fromtimestamp(date_range[1] / 1000).strftime("%Y-%m-%d")
                console.print(f"  Range: {s} → {e}")
        except Exception as e:
            console.print(f"[red]ERR Error: {redact_secrets(str(e))}[/]")
            raise typer.Exit(code=1) from e


@app.command()
def download_bybit(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (e.g. BTC/USDT)"),
    timeframe: str = typer.Option("1d", help="K-line timeframe (1m/5m/1h/4h/1d/...)"),
    start: str = typer.Option("2024-01-01", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option("2025-01-01", help="End date (YYYY-MM-DD)"),
    category: str = typer.Option("spot", help="Bybit market: spot / linear / inverse"),
    exchange_suffix: bool = typer.Option(True, help="Append -BYBIT suffix for source isolation"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Download historical klines from Bybit V5 (via CCXT).

    Stored with a ``-BYBIT`` suffix (e.g. ``BTC/USDT-BYBIT``) for exchange
    isolation — the symbol validator rejects ``.`` but allows ``-``.

    Examples:
        quantflow download-bybit --symbol BTC/USDT --timeframe 1d --start 2020-01-01
        quantflow download-bybit --symbol ETH/USDT --timeframe 4h --start 2021-01-01 --category linear
    """
    from quantflow.data.bybit_fetcher import BybitFetcher
    from quantflow.data.cleaner import clean_ohlcv
    from quantflow.data.store import DataStore

    if category not in ("spot", "linear", "inverse"):
        raise typer.BadParameter("category must be 'spot', 'linear', or 'inverse'")
    if ":" in symbol and category != "linear":
        raise typer.BadParameter(
            "Bybit delivery contracts belong to the linear category; use --category linear"
        )

    from quantflow.data.bybit_common import bybit_store_symbol

    cfg = _load(config)
    store_symbol = bybit_store_symbol(symbol) if exchange_suffix else symbol

    async def _run() -> None:
        fetcher = BybitFetcher(cfg.data, category=category)
        store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
        try:
            with console.status("[bold blue]Connecting to Bybit..."):
                await fetcher.connect()
            console.print("[green]OK[/] Connected to Bybit")

            with console.status(
                f"[bold blue]Downloading {symbol} {timeframe} ({start} → {end}) [{category}]..."
            ):
                df = await fetcher.fetch_ohlcv(symbol, timeframe, start, end, category=category)
            if df.empty:
                console.print(
                    "[red]ERR No data fetched. Check the symbol, timeframe, and date range.[/]"
                )
                return
            console.print(f"[dim]Raw data: {len(df)} bars[/]")
            with console.status("[bold blue]Cleaning data..."):
                df = clean_ohlcv(df)
            with console.status("[bold blue]Saving to Parquet..."):
                store.save(df, store_symbol)
            date_range = store.get_date_range(store_symbol)
            console.print(
                f"[green]OK[/] Saved [bold]{len(df)}[/] bars for [bold]{store_symbol}[/] ({timeframe})"
            )
            if date_range:
                s = datetime.fromtimestamp(date_range[0] / 1000).strftime("%Y-%m-%d")
                e = datetime.fromtimestamp(date_range[1] / 1000).strftime("%Y-%m-%d")
                console.print(f"  Range: {s} → {e}")
        except Exception as e:
            console.print(f"[red]ERR Error: {redact_secrets(str(e))}[/]")
            raise typer.Exit(code=1) from e
        finally:
            await fetcher.disconnect()
            store.close()

    asyncio.run(_run())


@app.command()
def download_bybit_funding(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (e.g. BTC/USDT)"),
    days: int = typer.Option(365, min=1, help="Backfill window in days"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Backfill Bybit funding-rate history (V5, category=linear).

    Stored under meta_funding_rate/<symbol>-BYBIT/ for source isolation.

    Examples:
        quantflow download-bybit-funding --symbol BTC/USDT --days 365
    """
    from quantflow.data.bybit_meta_fetcher import BybitMetaFetcher
    from quantflow.data.store import DataStore

    cfg = _load(config)

    from quantflow.data.bybit_common import bybit_store_symbol

    fetcher = BybitMetaFetcher(cfg.data)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    since_ms = int(time.time() * 1000) - days * 86_400_000
    _run_meta_backfill(
        fetcher=fetcher,
        store=store,
        connect_status="[bold blue]Connecting to Bybit (meta)...",
        backfill_status=f"[bold blue]Backfilling Bybit funding for {symbol} ({days}d)...",
        since_ms=since_ms,
        fetch=lambda since: fetcher.fetch_funding_rate_history(symbol, since),
        save=lambda df: fetcher.save_funding(store, df, symbol),
        empty_msg="No funding data fetched. Check the symbol.",
        ok_msg=f"Saved [bold]{{rows}}[/] funding rows for [bold]{symbol}-BYBIT[/]",
        last_label="Last funding time",
        meta_kind="funding_rate",
        store_symbol=bybit_store_symbol(symbol),
    )


@app.command()
def download_bybit_oi(
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (e.g. BTC/USDT)"),
    period: str = typer.Option("1d", help="OI granularity: 5m/15m/30m/1h/4h/1d"),
    days: int = typer.Option(365, min=1, help="Backfill window in days"),
    mark_usd: bool = typer.Option(True, help="Compute open_interest_usd via mark-price-kline"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Backfill Bybit open-interest history (V5, time-series, category=linear).

    Stored under meta_open_interest/<symbol>-BYBIT/ for source isolation.

    Examples:
        quantflow download-bybit-oi --symbol BTC/USDT --period 1d --days 365
    """
    from quantflow.data.bybit_meta_fetcher import BybitMetaFetcher
    from quantflow.data.store import DataStore

    cfg = _load(config)
    # RV-007-003 fix: default '1D' failed our own whitelist; normalize case.
    period = period.lower()
    tf_map = {"5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
    if period not in tf_map:
        raise typer.BadParameter("period must be one of 5m/15m/30m/1h/4h/1d")

    from quantflow.data.bybit_common import bybit_store_symbol

    fetcher = BybitMetaFetcher(cfg.data)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    since_ms = int(time.time() * 1000) - days * 86_400_000
    _run_meta_backfill(
        fetcher=fetcher,
        store=store,
        connect_status="[bold blue]Connecting to Bybit (meta)...",
        backfill_status=f"[bold blue]Backfilling Bybit OI for {symbol} ({period}, {days}d)...",
        since_ms=since_ms,
        fetch=lambda since: fetcher.fetch_open_interest_history(
            symbol, tf_map[period], since, mark_usd=mark_usd
        ),
        save=lambda df: fetcher.save_open_interest(store, df, symbol),
        empty_msg="No OI data fetched. Check the symbol/period.",
        ok_msg=(
            f"Saved [bold]{{rows}}[/] OI rows for [bold]{symbol}-BYBIT[/] ({period})"
        ),
        last_label="Last OI timestamp",
        meta_kind="open_interest",
        store_symbol=bybit_store_symbol(symbol),
    )


@app.command()
def research(
    strategy: str = typer.Option("trend_following", help="Strategy name"),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    start: str = typer.Option("2024-01-01", help="Start date"),
    end: str = typer.Option("2025-01-01", help="End date"),
    timeframe: str = typer.Option(
        "1h",
        help="Bar timeframe filter (partitions may hold multiple TFs; mixing them invalidates results)",
    ),
    capital: float = typer.Option(10000.0, help="Initial capital"),
    fee: float = typer.Option(0.001, help="Trading fee rate"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Run strategy backtest research.

    Examples:
        quantflow research --strategy trend_following --symbol BTC/USDT
        quantflow research --strategy mean_reversion --capital 50000 --fee 0.002
    """
    from quantflow.data.store import DataStore
    from quantflow.strategy.research.backtest import BacktestEngine
    from quantflow.strategy.research.report import generate_report

    cfg = _load(config)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)

    try:
        # Load data
        start_ts = _date_to_ms(start)
        end_ts = _date_to_ms(end)
        # REV-024: resolve "-OKX"/"-BINANCE"/"-BYBIT" storage suffixes —
        # bare-symbol queries silently missed everything `download` wrote.
        resolved = store.resolve_symbol(symbol)
        if resolved != symbol:
            console.print(f"[dim]Using stored symbol {resolved}[/]")
        df = store.query(resolved, start=start_ts, end=end_ts, timeframe=timeframe)
        if df.empty:
            console.print(f"[red]No data for {resolved}. Run 'download' first.[/]")
            return

        # Set datetime index
        if "datetime" in df.columns:
            df = df.set_index("datetime")

        close = df["close"]

        # Select strategy
        strategy_factories = _get_strategy_factories()
        strategy_factory = strategy_factories.get(strategy)
        if not strategy_factory:
            console.print(
                f"[red]Unknown strategy: {strategy}. Available: {list(strategy_factories.keys())}[/]"
            )
            return

        console.print(f"[bold blue]Running backtest: {strategy} on {symbol}[/]")

        # Generate signals and run backtest
        strategy_instance = strategy_factory(None)
        entries, exits = strategy_instance.generate_signals(df)
        engine = BacktestEngine()
        result = engine.run_backtest(
            close,
            entries,
            exits,
            initial_capital=capital,
            fee=fee,
            strategy_id=strategy,
            symbol=symbol,
        )

        # Display report
        console.print(generate_report(result, format="markdown"))

    finally:
        # RV-007/M10: early returns above leaked the DuckDB connection.
        store.close()


@app.command()
def optimize(
    strategy: str = typer.Option("trend_following", help="Strategy name"),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    start: str = typer.Option("2024-01-01", help="Start date"),
    end: str = typer.Option("2025-01-01", help="End date"),
    timeframe: str = typer.Option(
        "1h",
        help="Bar timeframe filter (partitions may hold multiple TFs; mixing them invalidates results)",
    ),
    method: str = typer.Option("bayesian", help="Optimization method: bayesian | cmaes"),
    trials: int = typer.Option(200, help="Number of optimization trials"),
    capital: float = typer.Option(10000.0, help="Initial capital"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Run parameter optimization.

    Examples:
        quantflow optimize --strategy trend_following --method bayesian --trials 200
        quantflow optimize --strategy mean_reversion --method cmaes --trials 100
    """
    from quantflow.data.store import DataStore
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    cfg = _load(config)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)

    start_ts = _date_to_ms(start)
    end_ts = _date_to_ms(end)
    resolved = store.resolve_symbol(symbol)
    df = store.query(resolved, start=start_ts, end=end_ts, timeframe=timeframe)
    if df.empty:
        console.print(f"[red]No data for {resolved}. Run 'download' first.[/]")
        return

    if "datetime" in df.columns:
        df = df.set_index("datetime")

    close = df["close"]

    strategy_map = _get_strategy_specs()

    if strategy not in strategy_map:
        console.print(f"[red]Unknown strategy: {strategy}[/]")
        return

    strategy_cls, param_space = strategy_map[strategy]

    console.print(f"[bold blue]Optimizing {strategy} with {method} ({trials} trials)...[/]")

    def _signal_fn(close_series: pd.Series, **params: Any) -> tuple[pd.Series, pd.Series]:
        s = strategy_cls(params)
        sub_df = df.copy()
        sub_df["close"] = close_series.values
        return s.generate_signals(sub_df)

    optimizer = StrategyOptimizer()
    try:
        with console.status(f"[bold blue]运行 Optuna 优化中（{trials} trials）..."):
            result = optimizer.optimize(
                close=close,
                signal_fn=_signal_fn,
                param_space=param_space,
                n_trials=trials,
                method=method,
                initial_capital=capital,
            )
    except Exception as e:
        console.print(f"[red]ERR 优化失败：{redact_secrets(str(e))}[/]")
        console.print("  请检查参数空间、数据范围与策略 generate_signals 实现。")
        # DEF-REV011-C: a real failure must not report success to CI/cron.
        raise typer.Exit(code=1) from e
    finally:
        store.close()

    table = Table(title="Optimization Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Method", result["method"])
    table.add_row("Objective", result["objective"])
    table.add_row("Best Value", f"{result['best_value']:.4f}")
    table.add_row("Trials", str(result["n_trials"]))
    for k, v in result["best_params"].items():
        table.add_row(k, str(v))

    console.print(table)

    # H4: next-step guidance — strictly after console.print(table), before return.
    console.print(
        f"[dim]下一步：运行 [bold]quantflow validate --strategy {strategy} "
        f"--symbol {symbol} --method gate[/] 进行 GO/NO-GO 验证。[/]"
    )


@app.command()
def validate(
    strategy: str = typer.Option("trend_following", help="Strategy name"),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    start: str = typer.Option("2024-01-01", help="Start date"),
    end: str = typer.Option("2025-01-01", help="End date"),
    timeframe: str = typer.Option(
        "1h",
        help="Bar timeframe filter (partitions may hold multiple TFs; mixing them invalidates results)",
    ),
    method: str = typer.Option(
        "full",
        help=(
            "Validation: cpcv | dsr | pbo | wfo | full | gate | lookahead | "
            "causal_preflight | recursive | stress"
        ),
    ),
    groups: int = typer.Option(8, help="CPCV groups"),
    test_groups: int = typer.Option(2, help="CPCV test groups"),
    n_trials: int = typer.Option(100, help="Number of trials for DSR"),
    optimize_trials: int = typer.Option(50, help="Optimization trials per OOS validation window"),
    optimize_method: str = typer.Option("bayesian", help="Optimization method for OOS validation"),
    wfo_windows: int = typer.Option(5, help="Walk-forward windows"),
    capital: float = typer.Option(10000.0, help="Initial capital"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Run anti-overfitting validation.

    Methods:
        cpcv       — Combinatorial Purged Cross-Validation (PBO < 0.5)
        dsr        — Deflated Sharpe Ratio (DSR > 0.95)
        pbo        — Probability of Backtest Overfitting
        wfo        — Walk-Forward Optimization (OOS efficiency > 50%)
        full       — All validation methods
        gate       — GO/NO-GO decision gate (CPCV + DSR + WFO)
        lookahead  — Static look-ahead leak scan (no data needed)
        causal_preflight — Look-ahead + negative-shift AST preflight (no data needed)
        recursive  — Recursive indicator dependency scan (no data needed)
        stress     — Monte Carlo path-level stress (diagnostic, non-gate)

    Examples:
        quantflow validate --strategy trend_following --method gate
        quantflow validate --method cpcv --groups 10 --test-groups 3
        quantflow validate --method lookahead --strategy trend_following
        quantflow validate --method causal_preflight --strategy trend_following
        quantflow validate --method stress --strategy trend_following
    """
    from quantflow.data.store import DataStore

    strategy_specs = _get_strategy_specs()
    strategy_spec = strategy_specs.get(strategy)
    if not strategy_spec:
        console.print(f"[red]Unknown strategy: {strategy}[/]")
        return

    strategy_factory, param_space = strategy_spec
    strategy_instance = strategy_factory(None)

    # Static scans: no market data required (fail-open on missing parquet).
    if method == "causal_preflight":
        from quantflow.strategy.validation.causal_preflight import run_causal_preflight

        console.print("[bold blue]Running causal preflight (lookahead + negative shift)...[/]")
        preflight = run_causal_preflight(strategy_instance)
        _display_causal_preflight(preflight)
        return

    if method == "lookahead":
        from quantflow.strategy.validation.lookahead import scan_strategy

        console.print("[bold blue]Running static look-ahead leak scan on generate_signals...[/]")
        lookahead_report = scan_strategy(strategy_instance)
        _display_lookahead(lookahead_report)
        return

    if method == "recursive":
        from quantflow.strategy.validation.recursive import scan_recursive

        console.print("[bold blue]Running recursive indicator dependency scan...[/]")
        recursive_report = scan_recursive(type(strategy_instance))
        _display_recursive(recursive_report)
        return

    cfg = _load(config)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    start_ts = _date_to_ms(start)
    end_ts = _date_to_ms(end)
    resolved = store.resolve_symbol(symbol)
    df = store.query(resolved, start=start_ts, end=end_ts, timeframe=timeframe)
    if df.empty:
        console.print(f"[red]No data for {resolved}. Run 'download' first.[/]")
        store.close()
        return

    if "datetime" in df.columns:
        df = df.set_index("datetime")

    entries, exits = strategy_instance.generate_signals(df)
    close = df["close"]

    def _signal_fn(frame: pd.DataFrame, **params: Any) -> tuple[pd.Series, pd.Series]:
        s = strategy_factory(params)
        return s.generate_signals(frame)

    if method == "stress":
        from quantflow.strategy.research.backtest import BacktestEngine
        from quantflow.strategy.validation.monte_carlo import monte_carlo_stress

        console.print("[bold blue]Running Monte Carlo path-level stress test...[/]")
        bt = BacktestEngine().run_backtest(
            close,
            entries,
            exits,
            initial_capital=capital,
            fee=cfg.execution.taker_fee,
            strategy_id=strategy,
            symbol=symbol,
        )
        trade_returns = bt.trade_returns
        bar_returns = (
            bt.equity_curve.pct_change()
            .replace([float("inf"), float("-inf")], float("nan"))
            .fillna(0.0)
            .to_numpy(dtype=float)
        )
        results = monte_carlo_stress(
            trade_returns=trade_returns if len(trade_returns) >= 2 else None,
            bar_returns=bar_returns if len(bar_returns) >= 2 else None,
            n_paths=1000,
            initial_capital=capital,
            seed=0,
        )
        if not results:
            console.print(
                f"[yellow]Insufficient trade/return history for MC stress "
                f"(trades={len(trade_returns)}, bars={len(bar_returns)}).[/]"
            )
        for res in results:
            _display_monte_carlo(res)
        store.close()
        return

    try:
        if method == "cpcv":
            from quantflow.strategy.validation.cpcv import cpcv_backtest

            console.print("[bold blue]Running CPCV validation with train-window optimization...[/]")
            with console.status("[bold blue]CPCV 多路径回测中..."):
                result = cpcv_backtest(
                    close,
                    entries,
                    exits,
                    n_groups=groups,
                    n_test_groups=test_groups,
                    initial_capital=capital,
                    signal_fn=_signal_fn,
                    param_space=param_space,
                    data=df,
                    n_trials=optimize_trials,
                    method=optimize_method,
                )
            _display_cpcv(result)

        elif method == "dsr":
            from quantflow.strategy.research.backtest import BacktestEngine
            from quantflow.strategy.validation.dsr import deflated_sharpe_ratio

            # Chain run_backtest directly — reusing the `bt`/`res` names (bound to
            # BacktestResult/MonteCarloResult by the monte_carlo branch above) for a
            # BacktestEngine confused mypy into narrowing them, flagging run_backtest
            # / sharpe_ratio as missing attributes. Use a branch-local name.
            dsr_res = BacktestEngine().run_backtest(close, entries, exits, initial_capital=capital)
            console.print("[bold blue]Running DSR validation...[/]")
            with console.status("[bold blue]计算 Deflated Sharpe Ratio 中..."):
                result = deflated_sharpe_ratio(
                    dsr_res.sharpe_ratio, n_trials=n_trials, sample_length=len(close)
                )
            _display_dsr(result)

        elif method == "wfo":
            from quantflow.strategy.validation.wfo import walk_forward_optimization

            console.print(
                "[bold blue]Running Walk-Forward Optimization with OOS regeneration...[/]"
            )
            with console.status("[bold blue]Walk-Forward (rolling) 优化中..."):
                rolling = walk_forward_optimization(
                    close,
                    entries,
                    exits,
                    n_windows=wfo_windows,
                    mode="rolling",
                    initial_capital=capital,
                    signal_fn=_signal_fn,
                    param_space=param_space,
                    data=df,
                    n_trials=optimize_trials,
                    method=optimize_method,
                )
            with console.status("[bold blue]Walk-Forward (anchored) 优化中..."):
                anchored = walk_forward_optimization(
                    close,
                    entries,
                    exits,
                    n_windows=wfo_windows,
                    mode="anchored",
                    initial_capital=capital,
                    signal_fn=_signal_fn,
                    param_space=param_space,
                    data=df,
                    n_trials=optimize_trials,
                    method=optimize_method,
                )
            _display_wfo(rolling, anchored)

        elif method == "pbo":
            from quantflow.strategy.validation.pbo import probability_of_overfitting

            console.print("[bold blue]Running PBO validation...[/]")
            with console.status("[bold blue]计算 Probability of Backtest Overfitting 中..."):
                result = probability_of_overfitting(
                    close,
                    entries,
                    exits,
                    n_groups=groups,
                    n_test_groups=test_groups,
                    initial_capital=capital,
                )
            _display_pbo(result)

        elif method in ("full", "gate"):
            from quantflow.strategy.validation.gate import validation_gate

            console.print("[bold blue]Running Full Validation Gate with true OOS validation...[/]")
            # validation_gate runs all phases internally — single sequential with-block
            # (H2 constraint #4: Rich allows only one live console.status at a time).
            with console.status("[bold blue]运行完整验证门禁 (CPCV→DSR→WFO→PBO) 中..."):
                result = validation_gate(
                    close,
                    entries,
                    exits,
                    n_trials=n_trials,
                    cpcv_groups=groups,
                    cpcv_test_groups=test_groups,
                    wfo_windows=wfo_windows,
                    initial_capital=capital,
                    signal_fn=_signal_fn,
                    param_space=param_space,
                    data=df,
                    optimize_trials=optimize_trials,
                    optimize_method=optimize_method,
                )
            _display_gate(result)
    except Exception as e:
        console.print(f"[red]ERR 验证失败：{redact_secrets(str(e))}[/]")
        console.print("  请检查 CPCV 分组数、WFO 窗口、数据长度与策略 generate_signals 实现。")
        # DEF-REV011-C: align with download's exit-1-on-failure contract.
        raise typer.Exit(code=1) from e
    finally:
        store.close()


@app.command()
def run(
    mode: str = typer.Option("paper", help="Run mode: paper | sandbox | live"),
    strategy: str = typer.Option(
        "trend_following", help="Strategy name (comma-separated for multiple)"
    ),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol (legacy single-symbol)"),
    symbols: str = typer.Option(
        "", help="Trading symbols, comma-separated (e.g. BTC/USDT,ETH/USDT). Overrides --symbol."
    ),
    timeframe: str = typer.Option("1h", help="Market data timeframe"),
    # DEF-REV011-D: >=1 — sleep(0) would spin the poll loop hot.
    interval: int = typer.Option(60, min=1, help="Polling interval in seconds"),
    capital: float = typer.Option(100000.0, help="Initial capital"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Run strategy in paper or live mode.

    Modes:
        paper    — Local simulation (no API key needed)
        sandbox  — OKX testnet (requires API key)
        live     — OKX real trading (requires API key + capital)

    Examples:
        quantflow run --mode paper --strategy trend_following
        quantflow run --mode paper --strategy trend_following,mean_reversion
        quantflow run --mode paper --symbols BTC/USDT,ETH/USDT
    """
    from quantflow.monitoring.sink import create_default_sink
    from quantflow.strategy.engine import TradingSession

    cfg = load_config(config)
    cfg.execution.mode = mode

    strategy_factories = _get_strategy_factories()

    # Support multiple strategies
    strategy_names = [s.strip() for s in strategy.split(",")]
    strategies: list[StrategyBase] = []
    for name in strategy_names:
        factory = strategy_factories.get(name)
        if factory:
            strategies.append(factory(None))
        else:
            console.print(f"[red]Unknown strategy: {name}[/]")
            return

    console.print(f"[bold blue]Starting {mode} trading with {len(strategies)} strategy(ies)[/]")

    # M4-4.4: resolve multi-symbol list. --symbols overrides --symbol.
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else [symbol]
    console.print(f"[bold blue]Symbols: {', '.join(symbol_list)}[/]")

    # P1 T005: hard path A/B banner — prevent comparing daily paper PnL to gate.json.
    if mode == "paper":
        console.print(
            "[bold yellow]PATH NOTICE — paper daily session is Path A[/]\n"
            "  Path A: quantflow run --mode paper (NO nested direction gate)\n"
            "  Path B: python scripts/run_baseline0.py (nested gate; matches gate.json)\n"
            "  Do NOT compare Path A PnL to Baseline-0 gate.json / WFO OOS numbers.\n"
            "  See docs/research/baseline0-paper-run-checklist.md §0."
        )

    session = TradingSession(cfg, strategies, monitoring_sink=create_default_sink())

    async def _run_session() -> None:
        try:
            gateway_config = _load_gateway_config_from_env(
                mode=mode,
                sandbox=(mode == "sandbox"),
            )
            await session.start(mode=mode, gateway_config=gateway_config, symbols=symbol_list)
            console.print(f"[green]Session started in {mode} mode[/]")
            console.print("[yellow]Press Ctrl+C to stop[/]")

            await session.run_data_loop(
                symbol=symbol_list[0],
                timeframe=timeframe,
                interval_seconds=interval,
                symbols=symbol_list,
            )

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping session...[/]")
        except typer.BadParameter:
            # Config-validation errors (missing OKX env vars, bad mode) must
            # propagate to Typer's exit handler for a non-zero exit code + the
            # canonical usage message — H3's redacted Exception handler must not
            # swallow them into exit 0.
            raise
        except Exception as e:
            # OKXGateway/order exceptions may embed apiKey/passphrase/URL in error
            # body. redact_secrets (module-level import, main.py:19) is the
            # two-layer scrubber — never print raw str(e).
            console.print(f"[red]ERR 运行失败：{redact_secrets(str(e))}[/]")
            console.print("  请检查 gateway 配置、API key 与 symbol。")
        finally:
            await session.stop()
            console.print("[green]Session stopped[/]")

    asyncio.run(_run_session())


# REV-009/S4 back-compat re-exports (tests access cli_main._display_* / _signal_quality_*);
# assignment form survives isort force-single-line, unlike an import.
from quantflow.cli import render as _cli_render  # noqa: E402

_add_signal_quality_rows = _cli_render._add_signal_quality_rows
_display_causal_preflight = _cli_render._display_causal_preflight
_display_cpcv = _cli_render._display_cpcv
_display_dsr = _cli_render._display_dsr
_display_gate = _cli_render._display_gate
_display_lookahead = _cli_render._display_lookahead
_display_monte_carlo = _cli_render._display_monte_carlo
_display_pbo = _cli_render._display_pbo
_display_recursive = _cli_render._display_recursive
_display_wfo = _cli_render._display_wfo
_format_signal_quality = _cli_render._format_signal_quality
_signal_quality_summary = _cli_render._signal_quality_summary


@app.command()
def benchmark(
    bars: int = typer.Option(500, min=80, help="Synthetic OHLCV bars for local benchmarks"),
    trials: int = typer.Option(3, min=1, help="Optimization trials for the benchmark loop"),
    wfo_windows: int = typer.Option(2, min=1, help="WFO windows for validation benchmark"),
    test_target: str = typer.Option(
        "tests/unit/test_cli.py", help="Pytest target for test-runtime baseline"
    ),
    skip_subprocess: bool = typer.Option(
        False, "--skip-subprocess", help="Skip CLI startup and pytest subprocess baselines"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Print machine-readable benchmark metrics"
    ),
    min_query_rows_per_sec: float | None = typer.Option(
        None, "--min-query-rows-per-sec", help="Fail if data query throughput is lower"
    ),
    min_bars_per_sec: float | None = typer.Option(
        None, "--min-bars-per-sec", help="Fail if TradingSession throughput is lower"
    ),
    min_three_strategy_bars_per_sec: float | None = typer.Option(
        None,
        "--min-three-strategy-bars-per-sec",
        help="Fail if the three-strategy event hot path throughput is lower",
    ),
    min_orders_per_sec: float | None = typer.Option(
        None, "--min-orders-per-sec", help="Fail if paper order throughput is lower"
    ),
    max_backtest_ms: float | None = typer.Option(
        None, "--max-backtest-ms", help="Fail if backtest latency is higher"
    ),
) -> None:
    """Run a synthetic performance baseline across key QuantFlow paths."""
    from quantflow.cli.services.benchmark import BenchmarkRequest, BenchmarkService

    request = BenchmarkRequest(
        bars=bars,
        trials=trials,
        wfo_windows=wfo_windows,
        test_target=test_target,
        skip_subprocess=skip_subprocess,
        min_query_rows_per_sec=min_query_rows_per_sec,
        min_bars_per_sec=min_bars_per_sec,
        min_three_strategy_bars_per_sec=min_three_strategy_bars_per_sec,
        min_orders_per_sec=min_orders_per_sec,
        max_backtest_ms=max_backtest_ms,
    )
    result = BenchmarkService().run(request)

    if json_output:
        console.print_json(json.dumps(result.to_dict()))
    else:
        table = Table(title="QuantFlow Performance Baseline")
        table.add_column("Area", style="cyan")
        table.add_column("Metric", style="green")
        table.add_column("Value", style="magenta")
        for m in result.metrics:
            table.add_row(m.area, m.metric, m.display)
        console.print(table)

        for f in result.failures:
            console.print(
                f"[red]Benchmark threshold failed:[/] "
                f"{f.metric}={f.value} {f.unit} {f.operator} {f.threshold}"
            )

    if result.failures:
        raise typer.Exit(1)


@app.command()
def station(
    host: str = typer.Option("127.0.0.1", help="Station server bind host"),
    port: int = typer.Option(8088, min=1, max=65535, help="Station server port"),
) -> None:
    """Launch QuantFlow Station business frontend."""
    from quantflow.web.app import run_station

    console.print(f"[bold blue]Starting QuantFlow Station at http://{host}:{port}[/]")
    run_station(host=host, port=port)


@app.command()
def ai(
    action: str = typer.Argument(
        "rdagent",
        help=(
            "AI action: 'rdagent' (factor mining), 'research' (discovery→IC), "
            "'train' (train→validate), 'register' (gated registration → paper only), "
            "'bypass' (T036 validation-only lane — never live)"
        ),
    ),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol for factor evaluation"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
    model_id: str = typer.Option("", help="Model id for 'register' action"),
    registry_dir: str = typer.Option("", help="Model registry dir override"),
    features_csv: str = typer.Option("", help="CSV path with feature columns for 'train'"),
    close_csv: str = typer.Option("", help="CSV path with 'close' column for 'train'"),
    factors_json: str = typer.Option(
        "",
        help=(
            "Discovered-factors JSON from 'ai research' (train); "
            "empty → latest or IndicatorEngine fallback"
        ),
    ),
) -> None:
    """Run AI-layer workflows (RD-Agent factor mining / train / register).

    Examples:
        quantflow ai rdagent --symbol BTC/USDT
        quantflow ai research --symbol BTC/USDT
        quantflow ai train --symbol BTC/USDT
        quantflow ai train --symbol BTC/USDT --factors-json data/ai_factors/BTC_USDT/latest.json
        quantflow ai register --model-id model-xxx
    """
    if action == "rdagent" or action == "research":
        _ai_factor_mining(action, symbol, config)
    elif action == "train":
        _ai_train(symbol, config, features_csv, close_csv, factors_json)
    elif action == "register":
        _ai_register(model_id, config, registry_dir)
    elif action == "bypass":
        _ai_validation_bypass(symbol, config, registry_dir, factors_json)
    else:
        console.print(
            f"[red]Unknown AI action: {action}. "
            "Available: rdagent, research, train, register, bypass[/]"
        )


def _ai_factor_mining(action: str, symbol: str, config: str) -> None:
    """Factor discovery (rdagent) or discovery→IC pipeline (research).

    Always persists results under data/ai_factors/{symbol}/ (names/IC only).
    Degrades to pandas baseline when qlib/rdagent/LLM are unavailable.
    """
    from quantflow.strategy.rd_agent import RDAgentRunner, save_discovered_factors

    runner = RDAgentRunner()
    available, msg = runner.check_available()
    if not available:
        console.print("[yellow]Qlib not installed — using built-in baseline factor evaluation.[/]")
        console.print(f"[dim]{msg.splitlines()[0] if msg else ''}[/]")

    cfg = _load(config)
    from quantflow.data.store import store_scope

    with store_scope(cfg.data.parquet_dir, cfg.data.duckdb_path) as store:
        resolved = store.resolve_symbol(symbol)
        df = store.query(resolved)
        if df.empty:
            console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
            return
        if "datetime" in df.columns:
            df = df.set_index("datetime")

        console.print(f"[bold blue]Running factor mining on {symbol}[/]")
        factors = runner.discover_factors(df)

        selected = [f for f in factors if f.selected]
        table = Table(title=f"RD-Agent Factors — {symbol}")
        table.add_column("Factor", style="cyan")
        table.add_column("IC", justify="right")
        table.add_column("Rank IC", justify="right")
        table.add_column("Selected", justify="center")
        for f in factors:
            table.add_row(
                f.name,
                f"{f.ic:+.4f}",
                f"{f.rank_ic:+.4f}",
                "[green]OK[/]" if f.selected else "[red]ERR[/]",
            )
        console.print(table)
        console.print(
            f"[bold]{len(selected)}/{len(factors)} factors passed "
            f"IC>{runner.config.ic_threshold} gate "
            f"(target: {runner.config.min_selected})[/]"
        )
        saved = save_discovered_factors(
            factors,
            symbol=symbol,
            source="cli-" + action,
            train_rows=len(df),
        )
        console.print(f"[green]Saved factors → {saved}[/]")
        console.print(
            f"[dim]Train next: quantflow ai train --symbol {symbol} "
            f"--factors-json {saved.as_posix()}[/]"
        )


def _ai_train(
    symbol: str,
    config: str,
    features_csv: str = "",
    close_csv: str = "",
    factors_json: str = "",
) -> None:
    """Train an AI model from features + close and run the validation gate.

    Feature source preference:
    1. Explicit features_csv + close_csv
    2. factors_json / data/ai_factors/{symbol}/latest.json materialized factors
    3. IndicatorEngine FeatureStore fallback (explicit log)
    """
    from pathlib import Path

    import pandas as pd

    from quantflow.strategy.ai_training import AITrainingPipeline
    from quantflow.strategy.rd_agent import (
        FACTORS_DIR,
        load_discovered_factors,
        materialize_factor_frame,
    )

    cfg = _load(config)
    if features_csv and close_csv:
        features = pd.read_csv(features_csv)
        close = pd.read_csv(close_csv)["close"]
        console.print(f"[bold blue]Training from CSVs ({len(features)} rows)[/]")
    else:
        from quantflow.data.feature_store import FeatureStore
        from quantflow.data.store import store_scope
        from quantflow.indicators.engine import IndicatorEngine

        with store_scope(cfg.data.parquet_dir, cfg.data.duckdb_path) as store:
            resolved = store.resolve_symbol(symbol)
            df = store.query(resolved)
            if df.empty:
                console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
                return
            if "datetime" in df.columns:
                df = df.set_index("datetime")

            fj = factors_json.strip()
            if not fj:
                safe = symbol.replace("/", "_").replace("\\", "_")
                latest = FACTORS_DIR / safe / "latest.json"
                if latest.exists():
                    fj = str(latest)

            features = None
            close = df["close"]
            if fj:
                if not Path(fj).exists():
                    console.print(f"[yellow]factors-json not found: {fj} — falling back[/]")
                else:
                    factors = load_discovered_factors(fj)
                    features = materialize_factor_frame(df, factors, selected_only=True)
                    if features.empty or features.shape[1] == 0:
                        features = materialize_factor_frame(df, factors, selected_only=False)
                    if features is not None and not features.empty and features.shape[1] > 0:
                        close = df["close"].reindex(features.index)
                        console.print(
                            f"[bold blue]Training from discovered factors ({fj}) "
                            f"— {features.shape[1]} cols × {len(features)} rows[/]"
                        )
                    else:
                        console.print(
                            "[yellow]Discovered factors not materializable — "
                            "falling back to IndicatorEngine FeatureStore[/]"
                        )
                        features = None

            if features is None:
                engine = IndicatorEngine()
                fs = FeatureStore(cfg.data.parquet_dir, indicator_computer=engine)
                resolved_ml = store.resolve_symbol(symbol)
                raw = store.query(resolved_ml)
                features = fs.compute_features(symbol, int(raw["timestamp"].max()), [], store)
                close = raw["close"]
                console.print(
                    f"[bold blue]Training on IndicatorEngine features for {symbol} "
                    f"({len(features)} rows) — explicit fallback path[/]"
                )

    if "timestamp" in features.columns and "close" not in features.columns:
        features = features.drop(columns=["timestamp", "symbol", "computed_at"], errors="ignore")

    pipe = AITrainingPipeline(
        validation_kwargs={"cpcv_groups": 4, "cpcv_test_groups": 1, "wfo_windows": 3}
    )
    report = pipe.train(features, close, None, n_estimators=50, max_depth=3)

    # Persist the training report so 'ai register --model-id <id>' can consume it.
    import json

    model_id = f"model-{report.features_hash}"
    report_dir = Path("data/ai_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{model_id}.json"
    report_payload = report.to_dict()
    report_payload["model_id"] = model_id
    report_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    verdict = "[green]GO[/]" if report.decision == "GO" else "[red]NO-GO[/]"
    console.print(f"\n[bold]Validation gate: {verdict}[/]")
    console.print(f"  reason: {report.reason}")
    console.print(f"  samples: {report.n_samples} · features_hash: {report.features_hash}")
    console.print(f"  model: {report.model_cls}")
    console.print(f"  model_id: {model_id} (use 'ai register --model-id {model_id}')")
    if report.feature_importance:
        top = list(report.feature_importance.items())[:5]
        console.print("  top features: " + ", ".join(f"{k}={v:.3f}" for k, v in top))
    # P1 T006: promotion requires fee×slip grid (P0 cost_fidelity) — surface early.
    console.print(
        "[yellow]Register requires fee_slip_grid on the validation report "
        "(zero-cost + 0.1%/0.1% cells). Attach via cost_fidelity.attach_cost_fidelity "
        "or scripts/reframe_sensitivity_1h.py before GO→paper.[/]"
    )
    if (
        report.decision == "GO"
        and not report_payload.get("fee_slip_grid")
        and not (
            isinstance(report_payload.get("validation"), dict)
            and report_payload["validation"].get("fee_slip_grid")
        )
    ):
        console.print(
            "[red]This GO report has no fee_slip_grid — "
            "ai register will REJECT (cost fidelity fail-closed).[/]"
        )


def _ai_register(model_id: str, config: str, registry_dir: str = "") -> None:
    """Register a trained model (fail-closed: only GO reports register)."""
    import json
    from pathlib import Path

    from quantflow.strategy.model_registry import ModelRegistry

    cfg = _load(config)
    reg_dir = registry_dir or cfg.ai.registry_dir
    if not model_id:
        console.print("[red]--model-id is required for 'register' action[/]")
        return

    # Locate the latest training report (from 'train' action output dir).
    report_path = Path("data/ai_reports") / f"{model_id}.json"
    if not report_path.exists():
        # Fall back: any registry-style JSON with decision in registry dir.
        candidates = sorted(Path(reg_dir).glob(f"{model_id}.json"))
        if candidates:
            report_path = candidates[-1]
    if not report_path.exists():
        console.print(f"[red]No training report found for {model_id}. Run 'ai train' first.[/]")
        return

    report = json.loads(report_path.read_text(encoding="utf-8"))
    # Merge top-level cost / IC fields into the validation payload for registry.
    validation_report = dict(report.get("validation") or {})
    if "decision" not in validation_report:
        validation_report["decision"] = report.get("decision", "NO-GO")
    for key in ("fee_slip_grid", "cost_fidelity", "risk_ablation", "ic_metrics", "ic"):
        if key in report and key not in validation_report:
            validation_report[key] = report[key]

    # P1 T006: optional IC floor when research published ic_metrics.
    ic_block = validation_report.get("ic_metrics") or report.get("ic_metrics")
    if isinstance(ic_block, dict):
        try:
            abs_ic = abs(float(ic_block.get("mean_ic", ic_block.get("ic", 0.0))))
            threshold = float(ic_block.get("threshold", 0.03))
            if abs_ic < threshold:
                validation_report["decision"] = "NO-GO"
                validation_report["reason"] = f"IC gate failed: |IC|={abs_ic:.4f} < {threshold}"
        except (TypeError, ValueError):
            validation_report["decision"] = "NO-GO"
            validation_report["reason"] = "IC metrics unparseable — fail-closed"

    reg = ModelRegistry(reg_dir)
    entry = reg.register(
        model_id=model_id,
        model_cls=str(report.get("model_cls", "unknown")),
        features_hash=str(report.get("features_hash", "")),
        validation_report=validation_report,
    )
    color = "green" if entry["status"] == "paper" else "red"
    console.print(f"[{color}]model {model_id} status={entry['status']}[/]")
    console.print(f"  reason: {entry.get('reason', '')}")
    if entry["status"] != "paper":
        console.print(
            "[yellow]NO-GO / rejected models never enter paper trading "
            "(decision + cost fidelity + optional IC + W14 path).[/]"
        )
    console.print(
        "[dim]T036: AI register never promotes to live. "
        "promote_to_live only for non-bypass paper models + evidence.[/]"
    )


def _ai_validation_bypass(
    symbol: str,
    config: str,
    registry_dir: str = "",
    factors_json: str = "",
) -> None:
    """T036: RD-Agent → validation only (never live)."""
    from quantflow.strategy.ai_validation_bypass import run_ai_validation_bypass

    cfg = _load(config)
    reg_dir = registry_dir or cfg.ai.registry_dir
    from quantflow.data.store import store_scope

    with store_scope(cfg.data.parquet_dir, cfg.data.duckdb_path) as store:
        resolved = store.resolve_symbol(symbol)
        df = store.query(resolved)
        if df.empty:
            console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
            return
        if "datetime" in df.columns:
            df = df.set_index("datetime")

        console.print(
            f"[bold blue]AI validation bypass (T036) — {symbol}[/] [dim]live wire forbidden[/]"
        )
        result = run_ai_validation_bypass(
            symbol=symbol,
            ohlcv=df,
            register=True,
            registry_dir=reg_dir,
            factors_json=factors_json or None,
        )
        verdict = "[green]GO[/]" if result.decision == "GO" else "[red]NO-GO[/]"
        console.print(f"Validation gate: {verdict}")
        console.print(f"  model_id: {result.model_id}")
        console.print(f"  reason: {result.reason}")
        console.print(f"  factors: {result.n_selected}/{result.n_factors} selected")
        console.print(f"  report: {result.report_path}")
        console.print(f"  register: {result.registered_status}")
        console.print(f"  ai_lane: {result.ai_lane} · live_blocked={result.ai_live_blocked}")
        for note in result.notes:
            console.print(f"  [dim]{note}[/]")
        console.print(
            "[yellow]No promote_to_live from this path. "
            "Paper GO still needs fee×slip + funding_tca + paper_replay (W14).[/]"
        )


@app.command(name="new-strategy")
def new_strategy(
    strategy_id: str = typer.Argument(..., help="snake_case strategy id, e.g. my_alpha"),
    description: str = typer.Option("", help="Short description for module docstring"),
    force: bool = typer.Option(False, help="Overwrite existing scaffold files"),
    repo_root: str = typer.Option(".", help="Repository root (default: cwd)"),
) -> None:
    """Scaffold a new StrategyBase module + YAML + acceptance checklist (P1 T005).

    Does not auto-register into the catalog — follow the generated checklist.
    """
    from quantflow.strategy.scaffold import ScaffoldError, scaffold_strategy

    try:
        result = scaffold_strategy(
            strategy_id,
            repo_root=repo_root,
            force=force,
            description=description,
        )
    except ScaffoldError as exc:
        console.print(f"[red]scaffold failed: {exc}[/]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]Scaffolded strategy '{result.strategy_id}' ({result.class_name})[/]")
    for path in result.files_written:
        console.print(f"  wrote {path}")
    console.print(
        "[yellow]Next: implement signals, register in catalog, run research/validate. "
        "See checklist for Path A vs Path B (paper run ≠ baseline0 nested gate).[/]"
    )


@app.command("assert-elliott")
def assert_elliott(
    dir: str | None = typer.Option(
        None,
        "--dir",
        help="Package dir with cost_report.json / run_meta.json",
    ),
    build: bool = typer.Option(
        False,
        "--build",
        help="Build a synthetic Elliott cost package before assert",
    ),
    n_bars: int = typer.Option(80, "--n-bars", help="Bars when --build"),
    reseat: bool = typer.Option(
        True,
        "--reseat/--no-reseat",
        help="paper_replay reseat grid when --build (default on)",
    ),
    require_full: bool = typer.Option(
        True,
        "--require-full/--no-require-full",
        help="Fail if full register structure (path+cost+funding) fails",
    ),
) -> None:
    """W26b: assert Elliott cost-grid package structure (not auto-GO).

    Thin CLI over ``scripts/assert_elliott_cost_package.py``.
    Structure pass ≠ promotion; decision remains research/NO_GO.
    """
    import scripts.assert_elliott_cost_package as assert_mod

    argv: list[str] = []
    if build:
        argv.append("--build")
    if dir:
        argv.extend(["--dir", dir])
    argv.extend(["--n-bars", str(n_bars)])
    argv.append("--reseat" if reseat else "--no-reseat")
    argv.append("--require-full" if require_full else "--no-require-full")
    code = assert_mod.main(argv)
    if code != 0:
        console = _make_console()
        console.print(
            "[red]assert-elliott failed[/] (structure incomplete — not a GO signal either way)"
        )
        raise typer.Exit(code=code)
    _make_console().print(
        "[green]assert-elliott structure OK[/] (still not promotion_eligible / not auto-GO)"
    )


@app.command("freeze-b4")
def freeze_b4(
    run_dir: str = typer.Option(
        ...,
        "--run-dir",
        help="baseline4/<run_id> directory (never baseline3/)",
    ),
) -> None:
    """W26a: write adjudication_frozen.json under a B4 run dir (KEEP_B0 only)."""
    import scripts.freeze_baseline4_adjudication as freeze_mod

    code = freeze_mod.main(["--run-dir", run_dir])
    if code != 0:
        raise typer.Exit(code=code)
    _make_console().print(f"[green]B4 freeze written under[/] {run_dir}")


@app.command("eval-btc-overlay")
def eval_btc_overlay(
    start: str = typer.Option("2021-01-01", "--start"),
    end: str = typer.Option("2026-08-04", "--end"),
    overlay_weight: float = typer.Option(
        0.30, "--overlay-weight", help="Overlay sleeve weight (2026-08-11 primary default)"
    ),
    fee: float = typer.Option(
        0.001, "--fee", help="Fee on overlay rebalances (default taker 10bp)"
    ),
    slip: float = typer.Option(0.001, "--slip"),
    fast: int = typer.Option(96, "--fast", help="Overlay fast MA bars"),
    slow: int = typer.Option(400, "--slow", help="Overlay slow MA bars"),
    mode: str = typer.Option("reduce_off", "--mode", help="add_on | reduce_off"),
    sweep: bool = typer.Option(False, "--sweep", help="Sweep weights/modes for best excess"),
    out: str = typer.Option(
        "data/paper_replay/beta_overlay/eval.json",
        "--out",
        help="JSON report path",
    ),
) -> None:
    """Product-bar eval: BTC beta+overlay vs BTC HODL (not research PAPER-GO).

    Thin CLI over ``scripts/run_btc_beta_overlay_eval.py``.
    PASS = positive excess after stated costs; dual cost matrix in JSON.
    """
    import sys as _sys

    import scripts.run_btc_beta_overlay_eval as eval_mod

    argv: list[str] = [
        "--start",
        start,
        "--end",
        end,
        "--overlay-weight",
        str(overlay_weight),
        "--fee",
        str(fee),
        "--slip",
        str(slip),
        "--fast",
        str(fast),
        "--slow",
        str(slow),
        "--mode",
        mode,
        "--out",
        out,
    ]
    if sweep:
        argv.append("--sweep")
    # eval main reads argparse from sys.argv
    old = _sys.argv
    try:
        _sys.argv = ["run_btc_beta_overlay_eval.py", *argv]
        code = eval_mod.main()
    finally:
        _sys.argv = old
    if code != 0:
        raise typer.Exit(code=code)
    _make_console().print(
        f"[green]eval-btc-overlay written[/] {out} (product gate vs BTC HODL — see cost_matrix)"
    )


@app.command("kol-ingest")
def kol_ingest(
    action: str = typer.Argument(
        ...,
        help="export | poll | consensus",
    ),
    path: str = typer.Option("", "--path", help="Export JSON path (action=export)"),
    channel: str = typer.Option("", "--channel", help="Discord channel id (poll)"),
    limit: int = typer.Option(50, "--limit"),
    images: bool = typer.Option(False, "--images/--no-images"),
    ocr: str = typer.Option("none", "--ocr", help="none|auto|tesseract|vision_stub"),
    registry: str = typer.Option("quantflow/config/kol_registry.yaml", "--registry"),
    data_dir: str = typer.Option("data/kol_signals", "--data-dir"),
    window_hours: float = typer.Option(6.0, "--window-hours"),
    min_sources: int = typer.Option(2, "--min-sources"),
) -> None:
    """Ingest Discord KOL messages and build advisory consensus (no auto-trade).

    Thin CLI over ``scripts/kol_discord_ingest.py``.
    """
    import sys as _sys

    import scripts.kol_discord_ingest as kol_mod

    argv: list[str] = [
        "--registry",
        registry,
        "--data-dir",
        data_dir,
        action,
    ]
    if action == "export":
        if not path:
            _make_console().print("[red]--path required for export[/]")
            raise typer.Exit(code=2)
        argv.append(path)
        if images:
            argv.append("--images")
        argv.extend(["--ocr", ocr])
    elif action == "poll":
        if channel:
            argv.extend(["--channel", channel])
        argv.extend(["--limit", str(limit)])
        argv.append("--images" if images else "--no-images")
        argv.extend(["--ocr", ocr if ocr != "none" else "auto"])
    elif action == "consensus":
        argv.extend(
            [
                "--window-hours",
                str(window_hours),
                "--min-sources",
                str(min_sources),
            ]
        )
    else:
        _make_console().print("[red]action must be export|poll|consensus[/]")
        raise typer.Exit(code=2)

    old = _sys.argv
    try:
        _sys.argv = ["kol_discord_ingest.py", *argv]
        code = kol_mod.main()
    finally:
        _sys.argv = old
    if code != 0:
        raise typer.Exit(code=code)
    _make_console().print(
        f"[green]kol-ingest {action} done[/] (advisory only — auto_trade stays false)"
    )


@app.command()
def status() -> None:
    """Show current system status."""
    table = Table(title="QuantFlow Status")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")

    # Check data availability
    data_dir = Path("data/parquet")
    data_ready = data_dir.exists() and any(data_dir.rglob("*.parquet"))
    data_status = (
        f"Ready ({len(list(data_dir.rglob('*.parquet')))} files)"
        if data_ready
        else "No data — run 'download'"
    )

    # Check config
    config_path = resolve_config_path(DEFAULT_CONFIG_PATH)
    config_status = (
        f"Ready ({config_path.as_posix()})" if config_path.exists() else "Missing default.yaml"
    )

    # Check Docker
    docker_ok = False
    try:
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=5)
        docker_ok = result.returncode == 0
    except Exception:
        pass

    table.add_row("Version", __version__)
    table.add_row("Phase", "v0.6 paper-first (shared RP + AI pipeline)")
    table.add_row("Data Layer", data_status)
    table.add_row("Config", config_status)
    table.add_row("Indicators", "Ready (21 factors)")
    # REV-024: hardcoded list went stale as strategies were added — read the
    # live catalog instead.
    from quantflow.strategy.catalog import get_strategy_definitions

    table.add_row("Strategies", ", ".join(sorted(get_strategy_definitions())))
    table.add_row("Validation", "CPCV + DSR + PBO + WFO + Gate")
    table.add_row("Risk Engine", "Kelly + VaR/CVaR + Drawdown")
    table.add_row("Paper Trade", "Ready (PaperGateway)")
    table.add_row("OKX Gateway", "Ready (CCXT async + reconnect)")
    table.add_row("Kill Switch", "Ready")
    table.add_row("Monitoring", "Prometheus + Grafana + Alerts")
    table.add_row("Docker", "Ready" if docker_ok else "Not available")
    console.print(table)


if __name__ == "__main__":
    app()
