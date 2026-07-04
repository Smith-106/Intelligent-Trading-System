# F-008 — CLI elliott-wave命令 + elliott_wave.yaml配置 + VectorBT回测

> Role: subject-matter-expert | Related decisions: D1, D2

## Architecture

This feature provides the user-facing interface for the Elliott Wave trading system: CLI commands, configuration schema, and backtest integration. It operates across L3 (strategy) and the CLI layer, connecting the wave analysis pipeline to user interaction and verification.

### CLI Commands

The following CLI commands MUST be added to the existing `quantflow` Typer application:

```bash
# Wave analysis — run ZigZag + wave classification on historical data
quantflow elliott-wave analyze --symbol BTC/USDT --timeframe 4h --start 2024-01-01

# Wave backtest — run VectorBT backtest with ElliottWaveStrategy
quantflow elliott-wave backtest --symbol BTC/USDT --start 2023-01-01 --end 2024-12-31

# Fibonacci levels — compute and display critical levels for current wave
quantflow elliott-wave fib-levels --symbol BTC/USDT --timeframe 4h

# Multi-timeframe view — show wave counts across all timeframes
quantflow elliott-wave mtf --symbol BTC/USDT
```

### Configuration Schema (elliott_wave.yaml)

The configuration MUST be organized into sections matching the feature decomposition:

```yaml
strategy:
  name: elliott_wave
  type: elliott_wave
  description: "Elliott Wave impulse/correction trading with Fibonacci confirmation"

# F-001: ZigZag + Wave Identification
zigzag:
  thresholds: [0.03, 0.05, 0.08]
  consensus_ratio: 0.6
  bar_tolerance: 3
  fib_tolerance: 0.15

# F-002: Fibonacci + Critical Levels
fibonacci:
  retrace_ratios: [0.236, 0.382, 0.5, 0.618, 0.786]
  extension_ratios: [1.0, 1.272, 1.618, 2.618, 4.236]
  critical_w2: [0.5, 0.618]
  critical_w3: [1.618]
  critical_w4: [0.382, 0.5]
  critical_w5: [1.618, 2.618]

# F-003: Channel + Divergence
channel:
  enabled: true
  max_projection_bars: 20
divergence:
  macd_fast: 12
  macd_slow: 26
  macd_signal: 9
  volume_ma_period: 20
  volume_contraction_threshold: 0.7

# F-004: Strategy Rules
rules:
  w2_entry:
    enabled: true
    strength: 0.8
    retrace_zone: [0.5, 0.618]
    require_volume_contract: true
    require_divergence: true
  w3_entry:
    enabled: true
    strength: 1.0
    require_volume_expand: true
    volume_ma_period: 20
  w4_entry:
    enabled: true
    strength: 0.6
    retrace_zone: [0.382, 0.5]
    require_alternation: true
  w5_exit:
    enabled: true
    partial_strength: 0.7
    full_strength: 0.9
    require_divergence: true
  b_wave_exit:
    enabled: true
    strength: 0.5
    retrace_zone: [0.382, 0.618]

# F-005: Signal + Risk
invalidation:
  hard_stop_at_iron_law: true
  attempt_reclassification: true
  time_stop_multiplier: 1.5

# F-006: Scaling
scaling:
  trial_pct: 0.12
  scale_in_pct: 0.25
  chase_pct: 0.12
  max_position_pct: 0.60
  exit_partial_1: 0.50
  exit_partial_2: 0.30
  exit_final: 0.20

# F-007: Multi-Timeframe
timeframes:
  hierarchy: ["1W", "4H", "1H", "15min"]
  primary: "4H"

# Risk (existing QuantFlow integration)
risk:
  position_size_method: kelly_half
  stop_loss_atr_mult: 1.5
  take_profit_fib_extensions: [1.618, 2.618]

symbols:
  - BTC/USDT
  - ETH/USDT
```

### VectorBT Backtest Integration

The backtest MUST use VectorBT for vectorized simulation, consistent with the existing `research/` module. The ElliottWaveStrategy `generate_signals()` method produces `(entries, exits)` boolean Series that feed directly into `vbt.Portfolio.from_signals()`.

Key backtest metrics to compute:
- Win rate (target: >= 55%)
- Profit factor / win-loss ratio (target: >= 2:1)
- Maximum drawdown
- Sharpe ratio
- Wave-specific metrics: entry accuracy per rule (W2, W3, W4), invalidation frequency, scaling plan completion rate

### Current Code Assessment

The existing `cli/main.py` uses Typer with a `quantflow` app. The `elliott_wave.yaml` exists but contains only basic parameters. The `strategy/research/` module has VectorBT integration for other strategies.

## Interface Contract

```python
# CLI integration (in cli/main.py)
elliott_wave_app = Typer(name="elliott-wave", help="Elliott Wave analysis and trading")
app.add_typer(elliott_wave_app, name="elliott-wave")

# Backtest entry point
def run_elliott_wave_backtest(
    symbol: str,
    start: str,
    end: str,
    config_path: str = "quantflow/config/strategies/elliott_wave.yaml",
) -> BacktestResult:
    """Run VectorBT backtest with ElliottWaveStrategy."""
```

## Constraints (RFC 2119)

1. All CLI commands MUST follow the existing `quantflow` command pattern (Typer, Rich output). New commands MUST be added as a sub-Typer group `elliott-wave` to avoid cluttering the main command namespace.
2. The `elliott_wave.yaml` configuration MUST be the single source of truth for all wave-specific parameters. Hardcoded values in the strategy code MUST be limited to safe defaults and MUST be overridable by the YAML config.
3. Backtest results MUST include both aggregate metrics and per-rule metrics. Per-rule metrics MUST show: number of signals, win rate, average return, and average hold duration for each of the five wave rules.
4. The backtest MUST use the same `generate_signals()` method that the live strategy uses. No separate backtest-only logic is permitted. This ensures backtest-live consistency per the QuantFlow architecture constraint.
5. Configuration validation MUST be performed at strategy initialization. Invalid or out-of-range values (e.g., `consensus_ratio > 1.0`, `trial_pct > max_position_pct`) MUST raise a `ConfigurationError` before any trading logic executes.
6. The `analyze` command MUST display wave labels with confirmation status (tentative/probable/confirmed) and critical levels with prices. Output MUST use Rich tables for readability.
7. The `fib-levels` command MUST show all Fibonacci levels for the current wave context, with critical levels highlighted. Levels MUST be sorted by price.
8. Backtest performance MUST meet the acceptance criteria: win rate >= 55%, profit factor >= 2:1. If the initial backtest does not meet these criteria, the configuration MUST be flagged for optimization via Optuna (consistent with the existing optimization pipeline).

## Test Approach

- **CLI smoke tests**: Run each CLI command with minimal data and verify non-error output.
- **Config validation tests**: Load valid and invalid YAML files and verify that validation catches errors.
- **Backtest consistency tests**: Run backtest via CLI and programmatically, verify identical results.
- **Per-rule metrics tests**: Verify that per-rule metrics are computed correctly by comparing against manually labeled wave entries.
- **Regression tests**: Verify that existing `quantflow research` and `quantflow run` commands still work after adding the `elliott-wave` sub-commands.

## TODOs

- Design the Rich table layout for the `analyze` and `fib-levels` commands.
- Determine how to display multi-timeframe wave counts in a terminal (tabbed view vs. vertical stack).
- Define the `BacktestResult` data structure that includes per-rule metrics.
- Study whether the existing Optuna optimization pipeline can be reused for Elliott Wave parameter tuning.
- Investigate whether wave-specific backtest visualizations (wave labels on price chart, channel lines) can be generated as static images for CLI output.
