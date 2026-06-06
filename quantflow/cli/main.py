"""CLI entry point for QuantFlow."""

from __future__ import annotations

import asyncio
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
from quantflow.monitoring.logger import setup_logging

setup_logging()

if TYPE_CHECKING:
    import pandas as pd

    from quantflow.strategy.base import StrategyBase

StrategyFactory: TypeAlias = Callable[[dict[str, Any] | None], "StrategyBase"]
ParamSpace: TypeAlias = dict[str, tuple[Any, ...]]
ResultDict: TypeAlias = dict[str, Any]


def _get_strategy_factories() -> dict[str, StrategyFactory]:
    from quantflow.strategy.templates.elliott_wave import ElliottWaveStrategy
    from quantflow.strategy.templates.funding_rate import FundingRateStrategy
    from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
    from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy
    from quantflow.strategy.templates.momentum_rotation import MomentumRotationStrategy
    from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
    from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy

    def trend_following_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return TrendFollowingStrategy(params)

    def mean_reversion_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return MeanReversionStrategy(params)

    def elliott_wave_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return ElliottWaveStrategy(params)

    def volatility_breakout_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return VolatilityBreakoutStrategy(params)

    def funding_rate_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return FundingRateStrategy(params)

    def momentum_rotation_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return MomentumRotationStrategy(params)

    def ml_ensemble_factory(params: dict[str, Any] | None = None) -> StrategyBase:
        return MLEnsembleStrategy(params)

    return {
        "trend_following": trend_following_factory,
        "mean_reversion": mean_reversion_factory,
        "elliott_wave": elliott_wave_factory,
        "volatility_breakout": volatility_breakout_factory,
        "funding_rate": funding_rate_factory,
        "momentum_rotation": momentum_rotation_factory,
        "ml_ensemble": ml_ensemble_factory,
    }


def _get_strategy_specs() -> dict[str, tuple[StrategyFactory, ParamSpace]]:
    factories = _get_strategy_factories()
    return {
        "trend_following": (
            factories["trend_following"],
            {
                "fast_ma_period": (3, 15),
                "slow_ma_period": (30, 120),
                "rsi_oversold": (20, 40),
                "rsi_overbought": (60, 85),
                "atr_multiplier": (1.2, 3.0),
                "volume_threshold": (0.8, 2.0),
            },
        ),
        "mean_reversion": (
            factories["mean_reversion"],
            {
                "rsi_oversold": (20, 40),
                "rsi_overbought": (60, 85),
                "bb_std": (1.5, 3.0),
                "exit_rsi_overbought": (50, 75),
                "exit_rsi_oversold": (25, 50),
            },
        ),
        "elliott_wave": (
            factories["elliott_wave"],
            {
                "zigzag_threshold": (0.02, 0.08),
                "fib_tolerance": (0.10, 0.25),
                "atr_stop_mult": (1.0, 3.0),
            },
        ),
        "volatility_breakout": (
            factories["volatility_breakout"],
            {
                "atr_threshold": (1.2, 2.0),
                "atr_shrink_exit": (0.5, 0.9),
                "volume_threshold": (1.2, 2.0),
            },
        ),
        "funding_rate": (
            factories["funding_rate"],
            {
                "entry_threshold": (0.0005, 0.002),
                "exit_threshold": (0.0001, 0.0005),
                "oi_change_threshold": (0.02, 0.1),
            },
        ),
        "momentum_rotation": (
            factories["momentum_rotation"],
            {
                "lookback": (10, 40),
                "top_n": (1, 5),
                "stop_loss_pct": (0.01, 0.05),
            },
        ),
        "ml_ensemble": (
            factories["ml_ensemble"],
            {
                "entry_threshold": (0.5, 0.8),
                "exit_threshold": (0.2, 0.5),
            },
        ),
    }


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
            console.print(f"[red]✗ Error: {e}[/]")
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
    method: str = typer.Option("full", help="Validation: cpcv | dsr | pbo | wfo | full | gate"),
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
        cpcv   — Combinatorial Purged Cross-Validation (PBO < 0.5)
        dsr    — Deflated Sharpe Ratio (DSR > 0.95)
        pbo    — Probability of Backtest Overfitting
        wfo    — Walk-Forward Optimization (OOS efficiency > 50%)
        full   — All validation methods
        gate   — GO/NO-GO decision gate (CPCV + DSR + WFO)

    Examples:
        quantflow validate --strategy trend_following --method gate
        quantflow validate --method cpcv --groups 10 --test-groups 3
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
    entries, exits = strategy_instance.generate_signals(df)
    close = df["close"]

    def _signal_fn(frame: pd.DataFrame, **params: Any) -> tuple[pd.Series, pd.Series]:
        s = strategy_factory(params)
        return s.generate_signals(frame)

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
