# F-008 — CLI elliott-wave命令 + elliott_wave.yaml配置 + VectorBT回测

> Role: system-architect | Related decisions: D1

## Architecture

### Module Layout

CLI integration extends `quantflow/cli/main.py` with a new `elliott-wave` command group. Configuration extends the existing `elliott_wave.yaml` with full parameter coverage. Backtest integration uses the existing `quantflow/strategy/research/backtest.py` infrastructure.

```
quantflow/cli/main.py                 # CLI — NEW: elliott-wave command group
quantflow/config/strategies/elliott_wave.yaml  # Config — extended
quantflow/strategy/research/backtest.py        # L3 — existing VectorBT wrapper (reused)
```

### CLI Command Structure

```bash
quantflow elliott-wave analyze --symbol BTC/USDT --timeframe 4h
quantflow elliott-wave backtest --symbol BTC/USDT --start 2024-01-01 --end 2024-12-31
quantflow elliott-wave validate --symbol BTC/USDT --method gate
quantflow elliott-wave run --mode paper --symbol BTC/USDT
```

### Configuration Schema Extension

The existing `elliott_wave.yaml` is extended with complete parameter coverage:

```yaml
strategy:
  name: elliott_wave
  type: trend
  description: "Elliott Wave impulse/correction trading with Fibonacci confirmation"

params:
  # ZigZag parameters
  zigzag_threshold: 0.03
  zigzag_consensus_thresholds: [0.03, 0.05, 0.08]
  zigzag_min_overlap: 2
  
  # Wave classification
  fib_tolerance: 0.15
  use_divergence: true
  divergence_oscillators: ["rsi_14", "macd_histogram", "obv"]
  
  # Stop loss
  atr_stop_mult: 1.5
  hard_stop_enabled: true
  soft_stop_enabled: true

risk:
  position_size_method: kelly_half
  max_position_pct: 0.10
  stop_loss_atr_mult: 1.5
  take_profit_fib_extensions: [1.618, 2.618]

scaling:
  trial_pct: 0.125
  scale_in_pct: 0.25
  chase_pct: 0.125
  max_total_pct: 0.50
  exit_tier1_pct: 0.35
  exit_tier2_pct: 0.35

mtf:
  timeframes: ["1w", "4h", "1h", "15m"]
  alignment_mode: closed_only
  primary_timeframe: "4h"

symbols:
  - BTC/USDT
  - ETH/USDT

timeframe: 4h
```

### Backtest Integration

The `ElliottWaveStrategy` integrates with the existing VectorBT-based backtest infrastructure via `generate_signals()`. The backtest runner loads the strategy, computes indicators, and runs the vectorized signal generation.

## Interface Contract

### CLI Commands

```python
# quantflow/cli/main.py

app.add_typer(elliott_wave_app, name="elliott-wave")

@elliott_wave_app.command("analyze")
def analyze(symbol: str, timeframe: str = "4h", config: str = "elliott_wave.yaml") -> None: ...

@elliott_wave_app.command("backtest")
def backtest(
    symbol: str,
    start: str,
    end: str,
    config: str = "elliott_wave.yaml",
    output: str = "backtest_report.html",
) -> None: ...

@elliott_wave_app.command("validate")
def validate(symbol: str, method: str = "gate", config: str = "elliott_wave.yaml") -> None: ...

@elliott_wave_app.command("run")
def run(mode: str = "paper", symbol: str = "BTC/USDT", config: str = "elliott_wave.yaml") -> None: ...
```

### Config Loading

```python
@dataclass
class ElliottWaveConfig:
    params: ElliottWaveParams
    risk: RiskConfig
    scaling: WaveScalingConfig
    mtf: MTFConfig
    symbols: list[str]
    timeframe: str

def load_elliott_wave_config(path: str) -> ElliottWaveConfig: ...
```

## Constraints (RFC 2119)

- C-038: The `elliott-wave` CLI command group MUST follow the existing command pattern in `quantflow/cli/main.py` (Typer + Rich formatting).
- C-039: `elliott_wave.yaml` MUST contain all configurable parameters; hardcoded values in the strategy MUST NOT exist.
- C-040: The `backtest` command MUST use the existing `quantflow/strategy/research/backtest.py` infrastructure; no duplicate backtest logic.
- C-041: The `validate` command MUST integrate with the existing validation pipeline (CPCV, DSR, WFO, gate) from `quantflow/strategy/validation/`.
- C-042: Configuration validation MUST fail fast with clear error messages if required fields are missing or values are out of range.
- C-043: The `run` command MUST support all three modes: `backtest`, `paper`, `live`, using the existing `TradingSession` abstraction.

## Test Approach

- **Unit**: Test config loading with valid and invalid YAML files; verify that missing fields raise `ConfigError`. Test CLI command argument parsing.
- **Integration**: Run `quantflow elliott-wave backtest` end-to-end with BTC/USDT data; verify that the output report contains expected metrics (win rate, profit factor, max drawdown).
- **Regression**: Existing CLI commands (`quantflow research`, `quantflow optimize`) MUST continue to work after adding the new command group.

## TODOs

- Define the exact output format for `analyze` command (text summary, JSON, or both).
- Specify how `validate` command integrates with the existing `gate` validation module.
- Determine whether `run --mode live` requires additional confirmation prompts (safety measure).
