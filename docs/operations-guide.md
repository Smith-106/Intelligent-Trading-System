# QuantFlow 运营完整性模块 — 用户指南与运维手册

## 概述

本文档覆盖 QuantFlow v0.3 新增的运营完整性基础设施，包括：
- 线程安全订单管理 (G1)
- 对账引擎 (G2)
- 分布式追踪 (G3)
- 数据质量监控 (G4)
- 增强告警分类 (G5)

---

## 1. 线程安全订单管理 (G1)

### 1.1 功能说明

OrderManager 现在使用 `threading.RLock` 保护所有状态变更操作，防止多策略线程并发访问时的竞态条件。

### 1.2 使用方式

**无需修改现有代码** — 所有现有 API 保持完全兼容。线程安全是透明添加的。

新增 API:
```python
# 原子取消订单（线程安全）
success, reason = order_manager.cancel_order(order_id)
if not success:
    logger.warning("Cancel failed: %s", reason)
```

### 1.3 配置

无需额外配置。RLock 在 OrderManager 初始化时自动创建。

### 1.4 运维注意事项

- **性能影响**: <1ms 每次操作（经压力测试验证）
- **死锁预防**: 使用 RLock（可重入锁），同一线程可多次获取
- **异常安全**: 上下文管理器保证锁在异常时释放

---

## 2. 对账引擎 (G2)

### 2.1 功能说明

ReconciliationEngine 实现了 ISS-20260720-004 要求的对账基础设施：
- 后台对账循环（默认每 5 分钟）
- L4 组合 vs 交易所持仓快照比较
- 孤儿订单检测（通过 `query_open_orders()` API）
- 漂移检测（可配置阈值，默认 1%）
- HMAC 签名审计日志

### 2.2 启用方式

在 `quantflow/config/default.yaml` 中添加:
```yaml
reconciliation:
  enabled: true
  interval_minutes: 5
  drift_threshold_bps: 100  # 1% = 100 basis points
  order_staleness_seconds: 300  # 5 minutes
  audit_secret_key: "${RECONCILIATION_SECRET_KEY}"
  audit_log_dir: "logs/audit"
```

### 2.3 使用方式

```python
from quantflow.reconciliation import ReconciliationEngine, AuditLogger

# 初始化
audit = AuditLogger(
    secret_key=os.environ["RECONCILIATION_SECRET_KEY"],
    log_dir="logs/audit",
)
engine = ReconciliationEngine(
    portfolio_manager=portfolio,
    gateway=okx_gateway,
    audit_logger=audit,
    drift_threshold_bps=100,
)

# 一次性对账
report = await engine.run_daily_reconciliation()
print(report.summary())

# 启动后台循环
await engine.start_background_loop(interval_minutes=5)

# 停止后台循环
await engine.stop_background_loop()
```

### 2.4 运维手册

#### 日常检查
1. 查看审计日志: `logs/audit/audit-YYYY-MM-DD.jsonl`
2. 检查对账报告中的 `has_critical_issues` 字段
3. 监控 Prometheus 指标 `reconciliation_drift_bps`

#### 告警响应
- **CRITICAL (severity > 0.8)**: 立即检查持仓差异，可能需要暂停交易
- **WARNING (severity 0.5-0.8)**: 调查原因，可能是网络延迟导致
- **INFO (severity < 0.5)**: 记录并观察趋势

#### 故障排除
| 症状 | 可能原因 | 解决方案 |
|------|---------|---------|
| 对账循环未启动 | `enabled: false` 或配置缺失 | 检查 default.yaml |
| GatewayError 频繁 | 网络不稳定或 API 限流 | 检查连接状态，增加重试间隔 |
| 审计日志写入失败 | 磁盘空间不足或权限问题 | 检查 log_dir 权限和空间 |
| 漂移误报 | 阈值设置过低 | 调整 drift_threshold_bps |

#### 环境变量
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `RECONCILIATION_SECRET_KEY` | HMAC 签名密钥 | 无（必须设置） |

---

## 3. 分布式追踪 (G3)

### 3.1 功能说明

提供关联 ID 传播和 OpenTelemetry 集成：
- ContextVar 基础的关联 ID 自动传播
- `@traced` 装饰器用于异步函数追踪
- Structlog 处理器注入 correlation_id/trace_id/span_id
- 可选 OpenTelemetry 集成（Jaeger/Grafana Tempo）

### 3.2 启用方式

```yaml
tracing:
  enabled: true
  service_name: "quantflow"
  otel_enabled: false  # 设为 true 启用 OpenTelemetry
  otel_jaeger_host: "localhost"
  otel_jaeger_port: 6831
```

### 3.3 使用方式

```python
from quantflow.common.tracing import traced, get_correlation_id, TracingContext

# 装饰器方式（推荐）
@traced("order.submission")
async def submit_order(order: Order):
    logger.info("Submitting", extra={"correlation_id": get_correlation_id()})
    ...

# 上下文管理器方式（批量操作）
async with TracingContext("batch_reconciliation") as ctx:
    await reconcile_positions()
    await reconcile_orders()
    # 所有操作共享同一 correlation_id
```

### 3.4 运维手册

#### 日志查询
所有日志现在包含 `correlation_id` 字段，可用于跨模块追踪：
```bash
# 查询特定请求的完整链路
grep "correlation_id.*abc123" logs/quantflow.log
```

#### OpenTelemetry 部署（可选）
```yaml
# docker-compose.yaml 添加
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "6831:6831/udp"  # Agent
```

---

## 4. 数据质量监控 (G4)

### 4.1 功能说明

实时验证市场数据质量，防止陈旧/异常数据影响交易决策：
- 新鲜度检查（60 秒过期阈值）
- 价格连续性验证（5% 波动阈值）
- 成交量异常检测（10 倍均值阈值）
- 复合质量评分（0-1 标度）
- Prometheus 指标导出

### 4.2 启用方式

```yaml
dq_monitor:
  enabled: true
  max_staleness_seconds: 60
  price_spike_threshold: 0.05  # 5%
  volume_multiplier: 10.0
  min_quality_score: 0.7  # 70%
```

### 4.3 使用方式

```python
from quantflow.data.dq_monitor import DataQualityMonitor

monitor = DataQualityMonitor(redis_cache=redis)

async def on_bar(bar):
    result = await monitor.validate_bar(bar)
    if result.valid:
        await event_bus.publish(EventType.BAR, bar)
    else:
        logger.warning(
            "Bar rejected: %s (score=%.2f)",
            result.violations,
            result.score.overall_score
        )
```

### 4.4 运维手册

#### Prometheus 指标
| 指标名 | 类型 | 说明 |
|--------|------|------|
| `dq_monitor_violations_total` | Counter | 违规计数（按类型和交易对） |
| `dq_data_staleness_seconds` | Gauge | 数据过期秒数 |
| `dq_quality_score` | Histogram | 质量分数分布 |

#### 告警规则
```yaml
# prometheus/alert_rules.yml
groups:
  - name: data_quality
    rules:
      - alert: DataStaleness
        expr: dq_data_staleness_seconds > 60
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Data feed stale for {{ $labels.symbol }}"
      
      - alert: DataQualityLow
        expr: dq_quality_score < 0.5
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Data quality below threshold for {{ $labels.symbol }}"
```

---

## 5. 增强告警分类 (G5)

### 5.1 功能说明

扩展告警分类体系，支持智能路由：
- 15 个告警类别（AlertCategory）
- 4 个优先级（AlertPriority: P0-P3）
- 为后续路由矩阵和去重器奠定基础

### 5.2 告警类别

| 类别 | 说明 | 典型优先级 |
|------|------|-----------|
| `EXECUTION_FAILURE` | 订单执行失败 | P0 |
| `RECONCILIATION_DRIFT` | 对账漂移检测 | P0 |
| `ORPHAN_ORDER` | 孤儿订单检测 | P1 |
| `RISK_THRESHOLD` | 风控阈值触发 | P1 |
| `DATA_STALENESS` | 数据过期 | P2 |
| `SYSTEM_HEALTH` | 系统健康检查 | P3 |

### 5.3 使用方式

```python
from quantflow.monitoring.alerts import AlertManager, AlertLevel, AlertCategory, AlertPriority

# 现有 API 保持不变
await alert_manager.send("Position drift detected", level=AlertLevel.CRITICAL)

# 新增分类（用于后续路由）
category = AlertCategory.RECONCILIATION_DRIFT
priority = AlertPriority.P0_EMERGENCY
```

---

## 6. 部署检查清单

### 前置条件
- [ ] Python 3.11+ 已安装
- [ ] Redis 服务可用（DQ Monitor 需要）
- [ ] 环境变量 `RECONCILIATION_SECRET_KEY` 已设置
- [ ] `pip install -e ".[dev]"` 已执行

### 配置验证
- [ ] `default.yaml` 中 reconciliation/tracing/dq_monitor 配置正确
- [ ] 所有新功能默认 `enabled: false`（逐步启用）
- [ ] Prometheus scrape 配置包含新指标端口

### 功能验证
- [ ] `pytest tests/unit/test_order_manager_thread_safety.py -v` → 5 passed
- [ ] `python -c "from quantflow.reconciliation import ReconciliationEngine"` → OK
- [ ] `python -c "from quantflow.common.tracing import traced"` → OK
- [ ] `python -c "from quantflow.data.dq_monitor import DataQualityMonitor"` → OK

### 生产启用顺序
1. **Week 1**: 启用 G1 (线程安全) — 零配置，自动生效
2. **Week 2**: 启用 G3 (追踪) — 设置 `tracing.enabled: true`
3. **Week 3**: 启用 G4 (DQ Monitor) — 需要 Redis
4. **Week 4**: 启用 G2 (对账) — 需要 `RECONCILIATION_SECRET_KEY`
5. **Week 5**: 启用 G5 (告警分类) — 配合路由矩阵

---

## 7. 回滚方案

所有新功能通过配置开关控制，回滚只需：
```yaml
reconciliation:
  enabled: false
tracing:
  enabled: false
dq_monitor:
  enabled: false
```

重启服务后所有新功能禁用，系统恢复到 v0.2 行为。

---

*文档版本: v0.3-draft*  
*最后更新: 2026-08-02*  
*维护者: QuantFlow Team*

---

## 10. 组合优化 / Symbol-level Risk Parity (v0.5)

### 10.1 说明

`risk.portfolio_optimization` 默认关闭。开启后：

- `level: strategy`（默认）：按策略收益再平衡（s5 原行为）
- `level: symbol`：共享账本下按标的 close-to-close 波动做周期 risk parity

再平衡周期按**唯一 bar 时间戳**计数；sizing 为 `strategy_weight × symbol_weight`。

### 10.2 研究脚本

```bash
python scripts/multi_symbol_replay.py
python scripts/wfo_shared_rp.py
```

### 10.3 运维注意

- 默认关闭 → 不影响既有单策略回测基线
- silo risk_parity（分仓独立资金）与共享账本 RP **不可直接比较收益**
- 生产启用前须完成 WFO/OOS 与 fee/slip 敏感度报告
