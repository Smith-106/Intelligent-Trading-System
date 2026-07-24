"""CLI entry point for QuantFlow."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

import typer
from rich.console import Console
from rich.table import Table

from quantflow import __version__
from quantflow.common.config import AppConfig, load_config, resolve_config_path
from quantflow.common.redaction import redact_secrets
from quantflow.monitoring.logger import setup_logging
from quantflow.strategy.catalog import (
    get_strategy_factories as _catalog_strategy_factories,
)
from quantflow.strategy.catalog import (
    get_strategy_specs as _catalog_strategy_specs,
)

setup_logging()

if TYPE_CHECKING:
    import pandas as pd

    from quantflow.strategy.base import StrategyBase
    from quantflow.strategy.validation.lookahead import LookaheadReport
    from quantflow.strategy.validation.monte_carlo import MonteCarloResult

StrategyFactory: TypeAlias = Callable[[dict[str, Any] | None], "StrategyBase"]
ParamSpace: TypeAlias = dict[str, tuple[Any, ...]]
ResultDict: TypeAlias = dict[str, Any]


def _get_strategy_factories() -> dict[str, StrategyFactory]:
    return _catalog_strategy_factories()


def _get_strategy_specs() -> dict[str, tuple[StrategyFactory, ParamSpace]]:
    return _catalog_strategy_specs()


app = typer.Typer(
    name="quantflow",
    help="Personal Crypto quantitative trading system\n\nCommands: download → research → optimize → validate → run",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
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
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    timeframe: str = typer.Option("1d", help="K-line timeframe"),
    start: str = typer.Option("2024-01-01", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option("2025-01-01", help="End date (YYYY-MM-DD)"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Download historical data from OKX.

    Examples:
        quantflow download --symbol BTC/USDT --start 2024-01-01
        quantflow download --symbol ETH/USDT --timeframe 4h --start 2023-06-01
    """
    from quantflow.data.cleaner import clean_ohlcv
    from quantflow.data.fetcher import DataFetcher
    from quantflow.data.store import DataStore

    cfg = _load(config)

    async def _run() -> None:
        fetcher = DataFetcher(cfg.data)
        store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)

        try:
            with console.status("[bold blue]Connecting to OKX..."):
                await fetcher.connect()
            console.print("[green]✓[/] Connected to OKX")

            with console.status(
                f"[bold blue]Downloading {symbol} {timeframe} ({start} → {end})..."
            ):
                df = await fetcher.fetch_ohlcv(symbol, timeframe, start, end)

            if df.empty:
                console.print("[red]✗ No data fetched. Check symbol and date range.[/]")
                console.print("  Hint: valid symbols include BTC/USDT, ETH/USDT, SOL/USDT")
                return

            console.print(f"[dim]Raw data: {len(df)} bars[/]")

            with console.status("[bold blue]Cleaning data..."):
                df = clean_ohlcv(df)

            with console.status("[bold blue]Saving to Parquet..."):
                store.save(df, symbol)

            date_range = store.get_date_range(symbol)
            console.print(
                f"[green]✓[/] Saved [bold]{len(df)}[/] bars for [bold]{symbol}[/] ({timeframe})"
            )
            if date_range:
                from datetime import datetime

                s = datetime.fromtimestamp(date_range[0] / 1000).strftime("%Y-%m-%d")
                e = datetime.fromtimestamp(date_range[1] / 1000).strftime("%Y-%m-%d")
                console.print(f"  Range: {s} → {e}")
        except Exception as e:
            # odyssey-review RP2 (ISS-037): fetcher/gateway exceptions may embed
            # OKX apiKey/URL — scrub before printing to the operator's terminal.
            console.print(f"[red]✗ Error: {redact_secrets(str(e))}[/]")
            console.print("  Check your internet connection and symbol name.")
        finally:
            await fetcher.disconnect()
            store.close()

    asyncio.run(_run())


@app.command()
def research(
    strategy: str = typer.Option("trend_following", help="Strategy name"),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    start: str = typer.Option("2024-01-01", help="Start date"),
    end: str = typer.Option("2025-01-01", help="End date"),
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

    # Load data
    df = store.query(symbol)
    if df.empty:
        console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
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

    store.close()


@app.command()
def optimize(
    strategy: str = typer.Option("trend_following", help="Strategy name"),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
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

    df = store.query(symbol)
    if df.empty:
        console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
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
    result = optimizer.optimize(
        close=close,
        signal_fn=_signal_fn,
        param_space=param_space,
        n_trials=trials,
        method=method,
        initial_capital=capital,
    )

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
    store.close()


@app.command()
def validate(
    strategy: str = typer.Option("trend_following", help="Strategy name"),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    method: str = typer.Option(
        "full", help="Validation: cpcv | dsr | pbo | wfo | full | gate | lookahead | stress"
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
        stress     — Monte Carlo path-level stress (diagnostic, non-gate)

    Examples:
        quantflow validate --strategy trend_following --method gate
        quantflow validate --method cpcv --groups 10 --test-groups 3
        quantflow validate --method lookahead --strategy trend_following
        quantflow validate --method stress --strategy trend_following
    """
    from quantflow.data.store import DataStore

    cfg = _load(config)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    df = store.query(symbol)
    if df.empty:
        console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
        return

    if "datetime" in df.columns:
        df = df.set_index("datetime")

    strategy_specs = _get_strategy_specs()
    strategy_spec = strategy_specs.get(strategy)
    if not strategy_spec:
        console.print(f"[red]Unknown strategy: {strategy}[/]")
        return

    strategy_factory, param_space = strategy_spec
    strategy_instance = strategy_factory(None)

    if method == "lookahead":
        from quantflow.strategy.validation.lookahead import scan_strategy

        console.print("[bold blue]Running static look-ahead leak scan on generate_signals...[/]")
        report = scan_strategy(strategy_instance)
        _display_lookahead(report)
        store.close()
        return

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

    if method == "cpcv":
        from quantflow.strategy.validation.cpcv import cpcv_backtest

        console.print("[bold blue]Running CPCV validation with train-window optimization...[/]")
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

        bt = BacktestEngine()
        res = bt.run_backtest(close, entries, exits, initial_capital=capital)
        console.print("[bold blue]Running DSR validation...[/]")
        result = deflated_sharpe_ratio(
            res.sharpe_ratio, n_trials=n_trials, sample_length=len(close)
        )
        _display_dsr(result)

    elif method == "wfo":
        from quantflow.strategy.validation.wfo import walk_forward_optimization

        console.print("[bold blue]Running Walk-Forward Optimization with OOS regeneration...[/]")
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

    store.close()


@app.command()
def run(
    mode: str = typer.Option("paper", help="Run mode: paper | sandbox | live"),
    strategy: str = typer.Option(
        "trend_following", help="Strategy name (comma-separated for multiple)"
    ),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol"),
    timeframe: str = typer.Option("1h", help="Market data timeframe"),
    interval: int = typer.Option(60, min=0, help="Polling interval in seconds"),
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
    """
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

    if not strategies:
        console.print("[red]No valid strategies specified[/]")
        return

    console.print(f"[bold blue]Starting {mode} trading with {len(strategies)} strategy(ies)[/]")

    session = TradingSession(cfg, strategies)

    async def _run_session() -> None:
        try:
            gateway_config = _load_gateway_config_from_env(
                mode=mode,
                sandbox=(mode == "sandbox"),
            )
            await session.start(mode=mode, gateway_config=gateway_config)
            console.print(f"[green]Session started in {mode} mode[/]")
            console.print("[yellow]Press Ctrl+C to stop[/]")

            await session.run_data_loop(
                symbol=symbol,
                timeframe=timeframe,
                interval_seconds=interval,
            )

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping session...[/]")
        finally:
            await session.stop()
            console.print("[green]Session stopped[/]")

    asyncio.run(_run_session())


def _display_cpcv(result: ResultDict) -> None:
    table = Table(title="CPCV Validation Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Paths", str(result["n_paths"]))
    table.add_row("PBO", f"{result['pbo']:.3f}")
    table.add_row("OOS Efficiency", f"{result['oos_efficiency']:.3f}")
    table.add_row(
        "OOS Sharpe (mean±std)", f"{result['oos_sharpe_mean']:.3f}±{result['oos_sharpe_std']:.3f}"
    )
    table.add_row("OOS Sharpe (min)", f"{result['oos_sharpe_min']:.3f}")
    _add_signal_quality_rows(table, result.get("signal_quality", {}))
    status = "[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]"
    table.add_row("Status", status)
    console.print(table)


def _display_dsr(result: ResultDict) -> None:
    table = Table(title="Deflated Sharpe Ratio")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("DSR", f"{result['dsr']:.4f}")
    table.add_row("Observed Sharpe", f"{result['observed_sharpe']:.3f}")
    table.add_row(
        "Expected Max (N trials)", f"{result['expected_max_sharpe']:.3f} (N={result['n_trials']})"
    )
    status = "[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]"
    table.add_row("Status", status)
    console.print(table)


def _display_wfo(rolling: ResultDict, anchored: ResultDict) -> None:
    table = Table(title="Walk-Forward Optimization")
    table.add_column("Metric", style="cyan")
    table.add_column("Rolling", style="green")
    table.add_column("Anchored", style="green")
    table.add_row(
        "IS Sharpe", f"{rolling['is_sharpe_mean']:.3f}", f"{anchored['is_sharpe_mean']:.3f}"
    )
    table.add_row(
        "OOS Sharpe", f"{rolling['oos_sharpe_mean']:.3f}", f"{anchored['oos_sharpe_mean']:.3f}"
    )
    table.add_row(
        "OOS Efficiency", f"{rolling['oos_efficiency']:.3f}", f"{anchored['oos_efficiency']:.3f}"
    )
    for label, key in _SIGNAL_QUALITY_ROWS:
        table.add_row(
            label,
            _format_signal_quality(rolling.get("signal_quality", {}), key),
            _format_signal_quality(anchored.get("signal_quality", {}), key),
        )
    r_status = "PASSED" if rolling["passed"] else "FAILED"
    a_status = "PASSED" if anchored["passed"] else "FAILED"
    table.add_row("Decision", r_status, a_status)
    console.print(table)


def _display_pbo(result: ResultDict) -> None:
    table = Table(title="Probability of Backtest Overfitting")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("PBO", f"{result['pbo']:.3f}")
    table.add_row("Overfit Paths", f"{result['overfit_paths']}/{result['total_paths']}")
    table.add_row("IS Return (mean)", f"{result['is_return_mean']:.3f}")
    table.add_row("OOS Return (mean)", f"{result['oos_return_mean']:.3f}")
    table.add_row("Rank Correlation", f"{result['rank_correlation']:.3f}")
    status = "[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]"
    table.add_row("Status", status)
    console.print(table)


def _display_gate(result: ResultDict) -> None:
    console.print(f"\n[bold]VALIDATION GATE: {result['decision']}[/]")
    if "reason" in result:
        console.print(f"Reason: {result['reason']}")
    for check_name, check_result in result.get("checks", {}).items():
        passed = check_result.get("passed", False)
        status = "[green]✓[/]" if passed else "[red]✗[/]"
        console.print(f"  {status} {check_name}")
        if check_result.get("signal_quality"):
            console.print(f"    Signal quality: {_signal_quality_summary(check_result)}")
    console.print()


def _display_lookahead(report: LookaheadReport) -> None:
    """Render a static look-ahead scan report for one strategy."""
    verdict = "PASS" if report.passed else "FAIL"
    color = "green" if report.passed else "red"
    console.print(f"\n[bold {color}]LOOK-AHEAD SCAN: {report.strategy} — {verdict}[/]")
    console.print(f"Scanned: {', '.join(report.scanned_methods) or '(no generate_signals found)'}")
    if report.source_path:
        console.print(f"Source: {report.source_path}")
    if report.passed:
        console.print("[green]No masked-aggregation leaks detected.[/]")
        console.print()
        return
    table = Table(title=f"Look-ahead findings ({len(report.findings)})")
    table.add_column("Sev", style="cyan", no_wrap=True)
    table.add_column("Line", justify="right", no_wrap=True)
    table.add_column("Pattern", style="magenta")
    table.add_column("Snippet")
    for f in report.findings:
        sev_color = "bold red" if f.severity == "high" else "yellow"
        table.add_row(f"[{sev_color}]{f.severity}[/]", str(f.line), f.pattern, f.snippet[:60])
    console.print(table)
    console.print(
        "[yellow]Fix: capture the entry-bar value and forward-fill it for the "
        "position lifetime (profit_target_exit_series in "
        "strategy/templates/_runtime.py).[/]"
    )
    console.print()


def _display_monte_carlo(res: MonteCarloResult) -> None:
    """Render a Monte Carlo path-level stress result (diagnostic, non-gate)."""
    console.print(f"\n[bold cyan]MC STRESS — {res.method} (n_paths={res.n_paths})[/]")
    console.print("[yellow]Diagnostic only — does not alter the GO/NO-GO gate.[/]")
    table = Table(title=f"Path band ({res.method})")
    table.add_column("Metric", style="cyan")
    table.add_column("Observed", justify="right")
    table.add_column("P5 (worst)", justify="right", style="red")
    table.add_column("P50 (median)", justify="right")
    table.add_column("P95 (best)", justify="right", style="green")
    table.add_row(
        "Max drawdown",
        f"{res.observed_max_drawdown:.4f}",
        f"{res.p5_max_drawdown:.4f}",
        f"{res.p50_max_drawdown:.4f}",
        "—",
    )
    table.add_row(
        "Terminal return",
        f"{res.observed_terminal_return:.4f}",
        f"{res.p5_terminal_return:.4f}",
        "—",
        f"{res.p95_terminal_return:.4f}",
    )
    console.print(table)
    flag = (
        "[red]observed path was unusually lucky (>50% of resampled paths drew down worse)[/]"
        if res.prob_worse_drawdown > 0.5
        else "[green]observed drawdown is within the resampled band[/]"
    )
    console.print(f"P(path worse than observed dd) = {res.prob_worse_drawdown:.3f} — {flag}")
    console.print()


_SIGNAL_QUALITY_ROWS = (
    ("Signal Precision", "precision"),
    ("Signal Recall", "recall"),
    ("Signal Hit Rate", "hit_rate"),
    ("Signal Brier Score", "brier_score"),
    ("Signal OOS Sharpe", "oos_sharpe"),
)


def _format_signal_quality(quality: ResultDict, key: str) -> str:
    value = quality.get(key)
    return "n/a" if value is None else f"{float(value):.3f}"


def _add_signal_quality_rows(table: Table, quality: ResultDict) -> None:
    if not quality:
        return

    for label, key in _SIGNAL_QUALITY_ROWS:
        table.add_row(label, _format_signal_quality(quality, key))


def _signal_quality_summary(result: ResultDict) -> str:
    quality = result.get("signal_quality", {})
    return ", ".join(
        f"{key}={_format_signal_quality(quality, key)}" for _label, key in _SIGNAL_QUALITY_ROWS
    )


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
    import sys
    import tempfile
    from time import perf_counter

    import numpy as np
    import pandas as pd

    from quantflow.common.config import AppConfig
    from quantflow.common.models import Bar, Direction, OrderRequest, OrderSide
    from quantflow.data.feature_store import FeatureStore
    from quantflow.data.store import DataStore
    from quantflow.execution.engine import ExecutionEngine
    from quantflow.indicators.engine import IndicatorEngine
    from quantflow.strategy.base import StrategyBase, StrategyContext
    from quantflow.strategy.engine import TradingSession
    from quantflow.strategy.research.backtest import BacktestEngine
    from quantflow.strategy.research.optimizer import StrategyOptimizer
    from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
    from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
    from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy
    from quantflow.strategy.validation.wfo import walk_forward_optimization

    dates = pd.date_range("2024-01-01", periods=bars, freq="h", tz="UTC")
    rng = np.random.default_rng(42)
    close_values = 100.0 + np.cumsum(rng.normal(0.02, 0.8, bars))
    frame = pd.DataFrame(
        {
            "timestamp": [int(dt.timestamp() * 1000) for dt in dates],
            "datetime": dates,
            "open": close_values - 0.2,
            "high": close_values + 0.5,
            "low": close_values - 0.5,
            "close": close_values,
            "volume": rng.uniform(10.0, 100.0, bars),
            "symbol": "BTC/USDT",
            "timeframe": "1h",
        }
    )
    close = pd.Series(close_values, index=dates)
    rolling_mean = close.rolling(12, min_periods=1).mean()
    entries = (close > rolling_mean).fillna(False)
    exits = (close < rolling_mean).fillna(False)
    rows: list[tuple[str, str, str]] = []
    metrics: dict[str, float] = {}
    records: list[dict[str, str | float]] = []

    def _metric_key(area: str, metric: str) -> str:
        normalized = metric.lower().replace(" ", "_").replace("/", "_per_")
        return f"{area}.{normalized}"

    def _record(area: str, metric: str, value: float, unit: str) -> None:
        metrics[_metric_key(area, metric)] = value
        records.append(
            {
                "area": area,
                "metric": metric,
                "value": round(value, 6),
                "unit": unit,
            }
        )

    def _time(area: str, metric: str, action: Callable[[], Any]) -> Any:
        started_at = perf_counter()
        value = action()
        elapsed_ms = (perf_counter() - started_at) * 1000
        rows.append((area, metric, f"{elapsed_ms:.2f} ms"))
        _record(area, metric, elapsed_ms, "ms")
        return value

    def _throughput(area: str, metric: str, count: int, elapsed_ms: float) -> None:
        per_second = count / max(elapsed_ms / 1000, 1e-9)
        rows.append((area, metric, f"{per_second:.0f}/s"))
        _record(area, metric, per_second, "per_second")

    with tempfile.TemporaryDirectory() as tmp:
        store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
        _time("data", "save synthetic parquet", lambda: store.save(frame, "BTC/USDT"))

        started_at = perf_counter()
        queried = store.query(
            "BTC/USDT",
            start=int(frame["timestamp"].iloc[bars // 4]),
            end=int(frame["timestamp"].iloc[-1]),
            timeframe="1h",
            columns=("timestamp", "close", "volume"),
        )
        query_ms = (perf_counter() - started_at) * 1000
        rows.append(("data", "query projected range", f"{query_ms:.2f} ms"))
        _record("data", "query projected range", query_ms, "ms")
        _throughput("data", "query rows/sec", len(queried), query_ms)
        store.close()

    indicator_engine = IndicatorEngine()
    _time("indicators", "batch calculate all", lambda: indicator_engine.batch_calculate(frame))
    _time(
        "indicators",
        "compute requested subset",
        lambda: indicator_engine.compute_all(frame, ["rsi_14", "atr_14"]),
    )

    with tempfile.TemporaryDirectory() as tmp:
        feature_store = FeatureStore(
            str(Path(tmp) / "features"), str(Path(tmp) / "features.duckdb")
        )
        feature_frame = frame[["timestamp", "datetime", "close", "volume"]].copy()
        feature_frame["rsi_14"] = indicator_engine.compute_all(frame, ["rsi_14"])["rsi_14"]
        _time(
            "feature_store",
            "save feature partitions",
            lambda: feature_store.save_features("BTC/USDT", feature_frame),
        )

        feature_start = int(frame["timestamp"].iloc[bars // 4])
        feature_end = int(frame["timestamp"].iloc[-1])
        started_at = perf_counter()
        feature_rows = feature_store.load_features(
            "BTC/USDT",
            start=feature_start,
            end=feature_end,
        )
        feature_query_ms = (perf_counter() - started_at) * 1000
        rows.append(("feature_store", "load projected range", f"{feature_query_ms:.2f} ms"))
        _record("feature_store", "load projected range", feature_query_ms, "ms")
        _throughput("feature_store", "load rows/sec", len(feature_rows), feature_query_ms)
        feature_store.close()

    engine = BacktestEngine()
    _time("research", "backtest", lambda: engine.run_backtest(close, entries, exits))

    def _signal_fn(close_series: pd.Series, threshold: float = 1.0) -> tuple[pd.Series, pd.Series]:
        mean = close_series.rolling(12, min_periods=1).mean()
        return close_series > mean * threshold, close_series < mean * threshold

    optimizer = StrategyOptimizer(engine=engine)
    _time(
        "research",
        f"optimizer {trials} trials",
        lambda: optimizer.optimize(
            close,
            _signal_fn,
            {"threshold": (0.98, 1.02)},
            n_trials=trials,
            method="grid",
        ),
    )
    _time(
        "validation",
        "optimized WFO",
        lambda: walk_forward_optimization(
            close,
            entries,
            exits,
            n_windows=wfo_windows,
            signal_fn=lambda data, threshold=1.0: _signal_fn(data["close"], threshold),
            param_space={"threshold": (0.98, 1.02)},
            data=pd.DataFrame({"close": close}, index=close.index),
            n_trials=trials,
            method="grid",
        ),
    )

    class NoSignalStrategy(StrategyBase):
        def __init__(self) -> None:
            super().__init__(name="benchmark_no_signal")

        def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
            if bar.close < 0:
                ctx.emit_signal(bar.symbol, Direction.LONG, 1.0, bar.close, self.name)

        def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            empty = pd.Series(False, index=df.index)
            return empty, empty

    async def _runtime_baselines() -> None:
        def _bar_from_row(row: Any) -> Bar:
            return Bar(
                symbol="BTC/USDT",
                timestamp=int(row.timestamp),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )

        strategy = NoSignalStrategy()
        session = TradingSession(AppConfig(), [strategy])
        await session.start(mode="paper")
        try:
            bar_slice = frame.tail(min(bars, 200))
            started = perf_counter()
            for row in bar_slice.itertuples(index=False):
                await session.on_bar(_bar_from_row(row))
            elapsed_ms = (perf_counter() - started) * 1000
            rows.append(("runtime", "TradingSession.on_bar batch", f"{elapsed_ms:.2f} ms"))
            _record("runtime", "TradingSession.on_bar batch", elapsed_ms, "ms")
            _throughput("runtime", "bars/sec", len(bar_slice), elapsed_ms)
        finally:
            await session.stop()

        hot_path_bars = max(bars, 2000)
        hot_rng = np.random.default_rng(142)
        hot_dates = pd.date_range("2024-06-01", periods=hot_path_bars, freq="min", tz="UTC")
        hot_close = 100.0 + np.cumsum(hot_rng.normal(0.01, 0.6, hot_path_bars))
        hot_frame = pd.DataFrame(
            {
                "timestamp": [int(dt.timestamp() * 1000) for dt in hot_dates],
                "open": hot_close - 0.2,
                "high": hot_close + 0.5,
                "low": hot_close - 0.5,
                "close": hot_close,
                "volume": hot_rng.uniform(10.0, 100.0, hot_path_bars),
            }
        )
        hot_strategies = [
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
            VolatilityBreakoutStrategy(),
        ]
        hot_contexts = [StrategyContext() for _ in hot_strategies]
        for hot_strategy, hot_context in zip(hot_strategies, hot_contexts, strict=True):
            hot_strategy.on_init(hot_context)

        started = perf_counter()
        for row in hot_frame.itertuples(index=False):
            hot_bar = _bar_from_row(row)
            for hot_strategy, hot_context in zip(hot_strategies, hot_contexts, strict=True):
                hot_strategy.on_bar(hot_context, hot_bar)
                hot_context.flush_signals()
        elapsed_ms = (perf_counter() - started) * 1000
        rows.append(("runtime", "three strategy on_bar batch", f"{elapsed_ms:.2f} ms"))
        _record("runtime", "three strategy on_bar batch", elapsed_ms, "ms")
        _throughput("runtime", "three strategy bars/sec", len(hot_frame), elapsed_ms)

        execution = ExecutionEngine()
        await execution.start(mode="paper")
        try:
            started = perf_counter()
            for _ in range(25):
                await execution.submit_order(
                    OrderRequest(
                        symbol="BTC/USDT",
                        side=OrderSide.BUY,
                        order_type="market",
                        quantity=0.001,
                        price=float(close.iloc[-1]),
                        strategy_id="benchmark",
                    )
                )
            elapsed_ms = (perf_counter() - started) * 1000
            rows.append(("execution", "paper submit_order batch", f"{elapsed_ms:.2f} ms"))
            _record("execution", "paper submit_order batch", elapsed_ms, "ms")
            _throughput("execution", "orders/sec", 25, elapsed_ms)
        finally:
            await execution.stop()

    asyncio.run(_runtime_baselines())

    if not skip_subprocess:
        _time(
            "cli",
            "startup --help",
            lambda: subprocess.run(
                [sys.executable, "-m", "quantflow.cli.main", "--help"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            ),
        )
        _time(
            "test",
            f"pytest {test_target}",
            lambda: subprocess.run(
                [sys.executable, "-m", "pytest", test_target, "-q"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            ),
        )

    threshold_checks = [
        (
            "data.query_rows_per_sec",
            metrics.get("data.query_rows_per_sec"),
            min_query_rows_per_sec,
            ">=",
            "per_second",
        ),
        (
            "runtime.bars_per_sec",
            metrics.get("runtime.bars_per_sec"),
            min_bars_per_sec,
            ">=",
            "per_second",
        ),
        (
            "runtime.three_strategy_bars_per_sec",
            metrics.get("runtime.three_strategy_bars_per_sec"),
            min_three_strategy_bars_per_sec,
            ">=",
            "per_second",
        ),
        (
            "execution.orders_per_sec",
            metrics.get("execution.orders_per_sec"),
            min_orders_per_sec,
            ">=",
            "per_second",
        ),
        (
            "research.backtest",
            metrics.get("research.backtest"),
            max_backtest_ms,
            "<=",
            "ms",
        ),
    ]
    failures = []
    for key, value, threshold, operator, unit in threshold_checks:
        if threshold is None or value is None:
            continue
        failed = value < threshold if operator == ">=" else value > threshold
        if failed:
            failures.append(
                {
                    "metric": key,
                    "value": round(value, 6),
                    "operator": operator,
                    "threshold": threshold,
                    "unit": unit,
                }
            )

    if json_output:
        console.print_json(
            json.dumps(
                {
                    "params": {
                        "bars": bars,
                        "trials": trials,
                        "wfo_windows": wfo_windows,
                        "test_target": test_target,
                        "skip_subprocess": skip_subprocess,
                    },
                    "metrics": records,
                    "failures": failures,
                }
            )
        )
    else:
        table = Table(title="QuantFlow Performance Baseline")
        table.add_column("Area", style="cyan")
        table.add_column("Metric", style="green")
        table.add_column("Value", style="magenta")
        for area, metric, display_value in rows:
            table.add_row(area, metric, display_value)
        console.print(table)
        for failure in failures:
            console.print(
                "[red]Benchmark threshold failed:[/] "
                f"{failure['metric']}={failure['value']} {failure['unit']} "
                f"{failure['operator']} {failure['threshold']}"
            )

    if failures:
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
        "rdagent", help="AI action: 'rdagent' (Qlib RD-Agent factor mining)"
    ),
    symbol: str = typer.Option("BTC/USDT", help="Trading symbol for factor evaluation"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, help="Config file path"),
) -> None:
    """Run AI-layer workflows (Qlib RD-Agent factor mining).

    Examples:
        quantflow ai rdagent --symbol BTC/USDT
    """
    if action != "rdagent":
        console.print(f"[red]Unknown AI action: {action}. Available: rdagent[/]")
        return

    from quantflow.data.store import DataStore
    from quantflow.strategy.rd_agent import QlibNotAvailableError, RDAgentRunner

    runner = RDAgentRunner()
    available, msg = runner.check_available()
    if not available:
        # Optional dependency missing — print install hint and exit cleanly.
        console.print("[yellow]Qlib RD-Agent not available.[/]")
        console.print(msg)
        return

    cfg = _load(config)
    store = DataStore(cfg.data.parquet_dir, cfg.data.duckdb_path)
    try:
        df = store.query(symbol)
        if df.empty:
            console.print(f"[red]No data for {symbol}. Run 'download' first.[/]")
            return
        if "datetime" in df.columns:
            df = df.set_index("datetime")

        console.print(f"[bold blue]Running RD-Agent factor mining on {symbol}[/]")
        try:
            factors = runner.discover_factors(df)
        except QlibNotAvailableError as e:
            console.print(f"[yellow]{e}[/]")
            return

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
                "[green]✓[/]" if f.selected else "[red]✗[/]",
            )
        console.print(table)
        console.print(
            f"[bold]{len(selected)}/{len(factors)} factors passed "
            f"IC>{runner.config.ic_threshold} gate "
            f"(target: {runner.config.min_selected})[/]"
        )
    finally:
        store.close()


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
    table.add_row("Phase", "3 (OKX Live + AI Factors)")
    table.add_row("Data Layer", data_status)
    table.add_row("Config", config_status)
    table.add_row("Indicators", "Ready (21 factors)")
    table.add_row(
        "Strategies",
        "trend_following, mean_reversion, elliott_wave, volatility_breakout, funding_rate, momentum_rotation, ml_ensemble",
    )
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
