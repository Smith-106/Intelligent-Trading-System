# TC-004 — SignalRiskLayer

| Field | Value |
|-------|-------|
| **ID** | TC-004 |
| **Type** | L4-signal-risk |
| **Features** | FT-006 (Risk Controls) |
| **Last Updated** | 2026-08-05T05:37:59Z |

## Code Locations

- `quantflow/signal/generator.py`
- `quantflow/signal/risk_engine.py`
- `quantflow/signal/position_sizer.py`
- `quantflow/signal/portfolio.py`
- `quantflow/signal/risk_metrics.py`
- `quantflow/signal/wave_signal_generator.py`
- `quantflow/signal/__init__.py`
- `quantflow/signal/optimizer.py`

## Exported Symbols

- `InvalidationEvent`
- `InvalidationSeverity`
- `MeanVarianceOptimizer` — Mean-variance portfolio optimizer (signal/optimizer.py)
- `PendingEntry` — Pending order entry record for exposure accounting
- `PendingView` — Pending-order view consumed by RiskEngine exposure gate
- `PortfolioManager`
- `PositionSizer`
- `RiskEngine`
- `RiskParityOptimizer` — Risk-parity portfolio optimizer (signal/optimizer.py)
- `SignalGenerator`
- `WaveInvalidationChecker`
- `WaveSignal`
- `WaveSignalGenerator`
- `bootstrap_cvar`
- `calmar_ratio`
- `conditional_var`
- `max_drawdown`
- `sharpe_ratio`
- `sortino_ratio`
- `value_at_risk`

## Dependencies

- Upstream: `quantflow/common` (models, exceptions, config).
- Downstream consumers: see feature maps for consumer wiring.

---

*Refreshed by codebase-refresh at 2026-08-05T05:39:39Z*
