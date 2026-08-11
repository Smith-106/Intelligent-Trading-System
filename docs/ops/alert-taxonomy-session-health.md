# Alert Taxonomy & Session Health (IMP-05)

**Date**: 2026-08-11  
**Scope**: ops readability — no Grafana redesign.

---

## 1. Alert levels (`AlertLevel`)

| Level | Meaning |
|-------|---------|
| `info` | Informational / batch |
| `warning` | Needs attention soon |
| `critical` | Immediate action |

## 2. Priorities (`AlertPriority`)

| Priority | SLA hint |
|----------|----------|
| `p0_emergency` | Immediate page / trading halt path |
| `p1_high` | Page within ~5 minutes |
| `p2_medium` | Notify within ~30 minutes |
| `p3_low` | Batch / next business day |

## 3. Sample routing (≥3 categories)

Resolved via `resolve_alert_channels(category, priority)` / `ALERT_ROUTING`:

| Category | Priority | Typical channels |
|----------|----------|------------------|
| `drawdown_breach` | P0 | telegram, line, webhook |
| `execution_failure` | P0 | telegram, webhook |
| `data_staleness` | P2 | telegram |
| `system_health` | P3 | webhook |

Full matrix: `quantflow/monitoring/alerts.py` (`ALERT_ROUTING`).

## 4. Session health metrics (Prometheus)

| Metric | Labels | Meaning |
|--------|--------|---------|
| `quantflow_session_health_up` | mode, strategy_id | 1=healthy, 0=down/halted |
| `quantflow_session_bars_processed` | mode, strategy_id | bars handled |
| `quantflow_session_last_bar_age_seconds` | mode, strategy_id | staleness |
| `quantflow_session_open_orders` | mode, strategy_id | open orders |

### Snapshot helper

```python
from quantflow.monitoring.session_health import build_session_health, alert_taxonomy_summary

snap = build_session_health(mode="paper", strategy_id="trend", bars_processed=10)
print(snap.status, snap.to_dict())
print(alert_taxonomy_summary())
```

### Query examples (PromQL)

```promql
quantflow_session_health_up{mode="paper"}
quantflow_session_last_bar_age_seconds > 3600
```

Existing portfolio gauges remain: `quantflow_portfolio_value`, `quantflow_portfolio_drawdown`, gateway/kill-switch counters.

---

## 5. PIT audit (IMP-03 cross-link)

```python
from quantflow.data.pit_audit import run_pit_audit_suite
# run_pit_audit_suite(feature_store, symbol=..., cutoff_ms=..., raw_store=...)
```

Docs: `tests/unit/test_feature_store_pit.py` + `tests/unit/test_pit_audit.py`.
