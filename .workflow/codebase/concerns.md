# QuantFlow 跨切面关注点报告（Cross-cutting Concerns）

> 本报告由 Mapper 4 基于实际代码（Read/Grep/Glob）编写，覆盖 QuantFlow 在错误处理、日志、配置、安全、测试、可观测性、事件解耦、数据安全、drift-realign 九个跨切面维度的实现机制与具体代码位置。
> 项目根：`c:\Users\niko\Desktop\智能交易系统`，Python 包：`quantflow/`。

---

## 1. 错误处理 & 异常（Error Handling & Exceptions）

**异常层次** — `quantflow/common/exceptions.py`
- 基类 `QuantFlowError(Exception)`，下挂分层异常：
  - `DataError` → `DataNotFoundError`、`DataValidationError`（L1 数据层）
  - `StrategyError` → `StrategyConfigError`（L3 策略层）
  - `SignalError` → `RiskBreachError`（风控越界）、`KillSwitchActivatedError`（熔断触发）
  - `ExecutionError` → `OrderError` → `OrderTimeoutError`，以及 `GatewayConnectionError`（L5 执行层）
  - `ConfigError`（配置层）
- 统一经 `quantflow/common/__init__.py` 重新导出，作为公共 API。
- `RiskBreachError` 携带 `reason` / `severity` 字段（severity 默认 `"warn"`，支持 `"critical"`）。
- 现状注记：`KillSwitchActivatedError` 与 `RiskBreachError` 当前主要出现在测试（`tests/unit/test_common_helpers.py`）中，生产代码多用 `RiskEngine.check()` 返回 `RiskDecision(passed=False, ...)`（见 `quantflow/common/models.py:199`）或 KillSwitch 直接置位，而非抛异常中断——属"失败不崩溃"设计。

**异常抛出点（raise）— 实证**
- `GatewayConnectionError`：L1 `quantflow/data/fetcher.py:86,98,153,208,230,269`（OKX 连接/未连接判断）。
- `DataError`：L1 `quantflow/data/redis_cache.py:53,75`、`quantflow/data/fetcher.py:100`、`quantflow/data/feature_store.py:126`（存储失败显式 raise，不再静默返回空 DF，ISS-20260723-014 GP1 修复）、`quantflow/data/store.py:168,209,257`（SQL 查询失败 `raise DataError(...) from e`）。

**EventBus 错误传播** — `quantflow/common/event_bus.py`
- `EventBus.publish()` / `publish_async()` 对 handler 内的异常统一 try/except，仅 `logger.error("Event handler error [%s]: %s", ...)`，**吞掉异常避免级联失败**（注释明确："Exceptions in handlers are caught and logged to prevent cascade failures"）。
- 同步 handler 在 `publish()` 内直接调用；async handler 在 `publish()` 中调度为 `asyncio.create_task`（不 await），在 `publish_async()` 中 await。异常都不会冒泡到发布者热路径。

---

## 2. 日志（Logging）

**结构化日志** — `quantflow/monitoring/logger.py`
- `setup_logging(level="INFO", json_format=False)` 通过 `structlog.stdlib.ProcessorFormatter` 桥接 stdlib `logging` 与原生 structlog，使二者共享同一 processor pipeline：
  - **structlog 端**：`structlog.configure(processors=shared + [ProcessorFormatter.wrap_for_formatter], logger_factory=structlog.stdlib.LoggerFactory(), wrapper_class=make_filtering_bound_logger(level), cache_logger_on_first_use=True)`，其中 `shared = [merge_contextvars, stdlib.add_log_level, StackInfoRenderer, set_exc_info, TimeStamper(fmt="iso")]`。
  - **stdlib 端**：`logging.config.dictConfig` 将 `ProcessorFormatter`（`foreign_pre_chain=shared`）挂到 root logger 的 `StreamHandler`——所有 `logging.getLogger(__name__)` 调用（全代码库 40+ 模块）经 `foreign_pre_chain` 接入同一 pipeline，与原生 structlog 记录统一渲染。
  - renderer：`ConsoleRenderer`（默认）或 `JSONRenderer`（`json_format=True`），经 `remove_processors_meta` 后输出。
- 这使规范声明 "structlog for structured logging" 对全代码库成立（DFT-7a3c1e9f，commit `3b35c3d`），而非仅原生 structlog 调用方。回归守卫 `tests/unit/test_logger_bridge.py`。
- 新模块用 `logging.getLogger(__name__)` 即可自动结构化，无需直接 import structlog（仅 `logger.py` 桥接点 import）。

**密钥脱敏** — `quantflow/common/redaction.py`
- `redact_secrets(text)` 双层脱敏：
  1. 字面 env 值：扫描 `SECRET_ENV_NAMES`（`OKX_API_KEY/OKX_SECRET/OKX_PASSPHRASE`、`QUANTFLOW_STATION_TOKEN`、`TELEGRAM_BOT_TOKEN`、`LINE_CHANNEL_ACCESS_TOKEN`、`REDIS_PASSWORD`、`GRAFANA_ADMIN_PASSWORD`），若在原串中出现则替换为 `***REDACTED***`。
  2. 形状匹配（即使 env 未设置也会脱敏，覆盖从配置/错误体泄漏的 token）：`_BOT_TOKEN_AFTER_PREFIX` / `_BOT_TOKEN_BARE`（Telegram bot token）、`_BEARER_PATTERN`（RFC 6750 Bearer）、`_REDIS_URL_PASSWORD_PATTERN`（redis://user:pass@host）。
- 为公共 API（无下划线前缀），被多层复用：web `session_manager` 快照、`app` 错误处理、`monitoring/metrics.py:167,168`、KillSwitch（`execution/kill_switch.py:85,99,105,132`）、AlertManager（`monitoring/alerts.py:30`）——单一审计面（G2 标准）。

**出栈 URL 安全** — `quantflow/common/url_safety.py`
- `validate_outbound_url(url, *, require_https=True)`：拒绝非 https（webhook）、非公开 IP（loopback/private/link-local/multicast/unspecified/reserved）、`localhost`、含 `userinfo` 的 URL；hostname 形式放行（DNS 交由 HTTP client 解析）。失败抛 `UnsafeUrlError(ValueError)`。
- 单一安全原语，被 `monitoring/alerts.py:143` 在 webhook 发送前调用（ISS-003 / SEC-010 SSRF 防护）。

---

## 3. 配置（Configuration）

**Pydantic v2 AppConfig** — `quantflow/common/config.py`
- `AppConfig(BaseModel)` 聚合子配置：`DataConfig`/`IndicatorConfig`/`ValidationConfig`/`StrategyConfig`/`RiskConfig`/`ExecutionConfig`/`MonitoringConfig`（顶层字段，默认工厂）。
- `load_config(config_path, cli_overrides=None)` 实现优先级：**CLI args (`cli_overrides`) > 环境变量 (`_load_env_overrides`, `QUANTFLOW_` 前缀，双下划线分层，如 `QUANTFLOW_RISK__MAX_DRAWDOWN`) > YAML 默认**（`yaml.safe_load`）。
- `save_config(config, config_path, sanitize=True)`：默认 `_sanitize_config` 剥离 `SENSITIVE_FIELDS = {token, secret, api_key, passphrase, password}`（及递归 dict/list），写入不泄露凭证。
- 路径安全：`resolve_config_path` 用于可信 CLI/内部调用；`resolve_config_path_safe` 用于 web 请求转发的 `config_path`，拒绝绝对路径与 `..` 遍历、约束在 packaged config 树内（防路径遍历读/写任意 YAML，ISS 凭据越权）。
- YAML 驱动策略/风控：`quantflow/config/default.yaml`（含 `risk.kill_switch_enabled: true`、`kelly_fraction`、`var_confidence` 等；注释记录多项历史 config-source 修复，如 ISS-20260721-012、ISS-20260723-005）。

**安全密钥治理**
- `.gitignore:24-27` 忽略 `.env` / `.env.local`（及 TLS/SSH/API key 物料），不入库。
- API Key 仅从环境变量读取：CLI 与 web 将 `OKX_API_KEY/OKX_SECRET/OKX_PASSPHRASE` 映射为 ccxt 配置（`cli/main.py:71-73`、`web/session_manager.py:43-45`），代码中不硬编码，且三者均登记在 `redaction.SECRET_ENV_NAMES` 用于脱敏。

---

## 4. 安全（Security）

**API Key 仅 env、绝不代码/日志**：见 §3；日志侧经 `redact_secrets` 全链路脱敏。

**Kill Switch 实盘强制**：`quantflow/strategy/engine.py:185-188` — `if mode == "live" and not self._config.risk.kill_switch_enabled: raise ... refusing to start`；`web/session_manager.py:167` 对 `live`/`sandbox` 模式同样校验。默认 `kill_switch_enabled: true`。`execution/kill_switch.py` 实现 fail-closed 紧急停止（取消挂单→reduceOnly 市价平仓→阻断新单），`query_positions` 失败返回 `status="failed"` 而非假成功（SEC-H5/REL-H8）。

**QuantFlow Station (aiohttp) 安全** — `quantflow/web/security.py` + `quantflow/web/app.py`
- `same_origin_guard` 中间件对 **所有变更方法**（POST/PUT/PATCH/DELETE）施加两层防护：
  1. **Bearer 共享密钥**：若 `QUANTFLOW_STATION_TOKEN` 设置，要求 `Authorization: Bearer <token>`，用 `hmac.compare_digest` 常量时间比较（防时序泄露）；token 每次请求从 env 读取（未缓存，便于轮换）。
  2. **CSRF same-origin**：当请求带 `Origin` 且与 `Host` 不匹配 → 403；`Origin` 缺失（非浏览器客户端 curl/TestClient，已具本地访问）放行。**已移除 `X-Requested-With` 旁路**（非禁止 CORS 头，曾被用作 CSRF 绕过，SEC-004）。
- **bind-boundary 启动守卫** — `app.py:357 run_station(host, port)`：若 `host` 非 loopback 且未设 `QUANTFLOW_STATION_TOKEN`，直接 `raise RuntimeError` 拒绝启动（防无认证暴露 23 个端点含实盘控制）。`create_app()` 本身 host 无关（便于测试，守卫只在 bind 边界）。
- 其他加固：`create_app` 注册 `rate_limit_middleware` + `client_max_size=MAX_REQUEST_BODY_BYTES` 限流与限制体大小（ISS-001 SEC-006/007，拒绝洪泛/内存放大）；`_same_origin_guard` 前置于 rate_limit。

**出栈 URL 校验 / 脱敏**：见 §2（`validate_outbound_url`、`redact_secrets`）。

---

## 5. 测试（Testing）

**pytest + pytest-asyncio** — `pyproject.toml`（[tool.pytest.ini_options]）
- `testpaths = ["tests"]`，`asyncio_mode = "auto"`（异步测试无需显式装饰）。
- markers：`slow`（慢测试）、`integration`（集成）、`live`（需真实 API 连接）。
- 覆盖率：`[tool.coverage.run] source=["quantflow"]`，`fail_under = 70`，`omit = tests/*, quantflow/cli/*`（核心模块 >70%）。
- 质量门禁（AGENTS.md）：`ruff check --fix && ruff format .`、`mypy quantflow/ --strict`（mypy 严格类型）。
- 目录：`tests/unit/`、`tests/integration/`；`@pytest.mark.live` 标记需 API 连接的用例，`@pytest.mark.slow` 标记慢用例。
- 状态记载：1411 tests pass（见 `.workflow/state.json` 项目状态）。

---

## 6. 监控 / 可观测性（Monitoring & Observability）

**Prometheus 指标** — `quantflow/monitoring/metrics.py`
- 计数器：`ORDERS_TOTAL`/`ORDERS_FILLED`/`SIGNALS_GENERATED`/`RISK_EVENTS`/`KILL_SWITCH_ACTIVATIONS`/`KILL_SWITCH_STEP_FAILURES`/`GATEWAY_CONNECTED`(Gauge)/`GATEWAY_DISCONNECTS`/`GATEWAY_RECONNECTS`/`ORDERS_TIMED_OUT`。
- Gauge：`PORTFOLIO_VALUE/CASH/DRAWDOWN`、`POSITIONS_COUNT`；Histogram：`ORDER_LATENCY`/`BAR_PROCESSING_LATENCY`/`SIGNAL_PROCESSING_LATENCY`。
- `start_metrics_server(port)` 按端口幂等（锁 + `_METRICS_SERVER_STATE`），启动失败经 `redact_secrets` 脱敏后写入 `last_error`/日志（ISS-035 CWE-209）。
- `metrics_registry_snapshot()` 返回紧凑快照（供 web/service 暴露）；`update_portfolio_metrics(...)` 更新组合 Gauge。

**AlertManager** — `quantflow/monitoring/alerts.py`
- `AlertManager.send(...)` 支持 Telegram / LINE / 通用 webhook；`AlertLevel`(info/warning/critical)。`_safe_alert_error` 经 `redact_secrets` 脱敏告警异常（Telegram URL 内嵌 bot token、LINE Bearer 头），所有错误走单一审计面。webhook 发送前 `validate_outbound_url(self.webhook_url)`（SSRF）。

**MonitoringSink 协议（L3/L4/L5 解耦 L6，arch-013 审计规避修复）** — `quantflow/common/monitoring_sink.py`
- `MonitoringSink`（runtime_checkable Protocol）是 L3/L4/L5 依赖的可观测性契约：`start`/`record_signal`/`record_bar_latency`/`record_signal_latency`/`record_portfolio`/`record_risk_event`/`record_kill_switch_activation`/`record_kill_switch_step_failure`/`record_order_total`/`record_order_filled`/`record_order_latency`/`record_gateway_connected`/`record_gateway_disconnect`/`record_gateway_reconnect`/`record_order_timed_out`/`send_alert`（全部 best-effort，不得冒泡进热路径）。
- `NullMonitoringSink` 为默认 no-op（测试/回测零耦合 L6）。
- 真实实现在 L6 `quantflow/monitoring/sink.py`，由 cli / session_manager **注入**（非 L3/L4/L5 import monitoring/）。这替换了此前 `RiskEngine`/`KillSwitch`/`ExecutionEngine` 内直接的 `RISK_EVENTS`/`KILL_SWITCH_ACTIVATIONS`/`ORDERS_TOTAL` 导入（ISS-20260724-044），消除 L6 跨层耦合与 lazy-import 审计规避。

---

## 7. 事件驱动解耦（Event-driven Decoupling）

**EventBus** — `quantflow/common/event_bus.py`
- 6 种核心事件类型（常量定义在 `quantflow/common/models.py:47-52`）：`EVENT_BAR="bar"`、`EVENT_TICK="tick"`、`EVENT_SIGNAL="signal"`、`EVENT_ORDER="order"`、`EVENT_FILL="fill"`、`EVENT_RISK="risk"`。
- `Event(type, data)` 不可变（slots）；`EventBus.subscribe/unsubscribe/publish/publish_async/clear/handler_count`；支持 sync+async handler，异常吞掉（见 §1）。

**策略不直接调用 Gateway**
- L3 `quantflow/strategy/engine.py`：`TradingSession` 持有 `EventBus`（`engine.py:97`，`event_bus` property `:747`），订阅 `EVENT_RISK`（`engine.py:198`），发布 SIGNAL/RISK 事件（`engine.py:252,394,412`）。
- L5 `quantflow/execution/engine.py`：ExecutionEngine 接收注入的 `EventBus`（`engine.py:47`），发 ORDER/FILL 事件（`engine.py:251-252,300-301,368-369`）——策略层只发信号，不直接 `send_order`。

**TradingSession 统一 backtest/paper/live** — `RunMode`（`common/models.py:39-42`：BACKTEST/PAPER/LIVE）；`TradingSession` 以同一事件循环驱动三种模式，回测-实盘一致（AGENTS.md 设计原则）。实盘模式强制 Kill Switch（§4）。

---

## 8. 数据安全 / 泄漏防控（Data Safety / Leak Prevention）

**FeatureStore 时间点安全** — `quantflow/data/feature_store.py`
- `compute_features(..., timestamp)` 用 `raw_store.query(symbol, end=timestamp)` 仅取 ≤timestamp 数据（无未来泄漏）；`load_features(start, end)` 用参数化 `?` 占位符（`params=[int(start), int(end)]`）拼 WHERE，杜绝 SQL 注入（`feature_store.py:103-120`）。
- 读写路径均 `validate_symbol(symbol)`（REV-008 防 parquet 目录遍历）；存储失败 `raise DataError`（GP1 不再静默）。

**validate_no_future_leak** — `quantflow/data/cleaner.py`
- `clean_ohlcv(..., validate_no_future_leak=True)` 默认开启（`cleaner.py:18,49`），调用 `_validate_no_future_leak`（`:153`）校验时间戳不来自未来，发现即告警"data leak"，可用参数关闭。导出在 `data/__init__.py`。

**MTFAligner 泄漏安全（HTF 索引移位）** — `quantflow/data/mtf_aligner.py`
- `_reindex_to_utc`（`mtf_aligner.py:183-214`）：HTF（高周期）OHLCV 仅在 bar 收盘后可知，CCXT 时间戳为 bar-open。修复将 HTF 索引 `df.index += period`（一个周期）后再 `reindex(aligned_index).ffill()`，使 HTF 值仅在下一 bar open（=当前 bar close）可见，避免 naive ffill 的多周期前视泄漏（deep-research F1/P0.1）。`_infer_period` 推断周期以决定移位量。

**静态前视泄漏扫描** — `quantflow/strategy/validation/lookahead.py`
- `scan_strategy`：对 `generate_signals(df)` 源码做 **AST 静态扫描**，标记对 `{entries,exits,mask,...}` 掩码序列做 `mean/sum/std/var/median/min/...` 聚合的前视模式（用全序列未来值污染入场 bar 决策，deep-research F2/P0.2）。**无需数据/回测**。
- CLI：`quantflow validate --strategy <name> --method lookahead`（`cli/main.py:361-366`，`_display_lookahead` `:705`）。

---

## 9. Drift / Realign 跟踪

- `.workflow/state.json`（version 2.0）为项目状态与里程碑机，当前 `status: active`、`current_milestone: M3`、`current_task_id: M3-P2`。
- 多处代码注释记录 **drift-realign / schema-drift / config-source 修复**，证明该机制被实际用于回归追踪，例如：
  - `common/config.py:46` — `StrategyConfig.research_engine` 注释：`drift-realign DFT-2c8d4f1e: vectorbt 已移除, default 改 eventdriven (BacktestEngine)。注: 字段当前零消费方 (schema-drift)`。
  - `common/config.py:62-87` — `kelly_fraction`/`var_confidence`/`fixed_pct`/`min_order_notional` 注释记录"之前硬编码导致 YAML 值被静默丢弃"的 config-source 修复（ISS-20260721-012 等）。
  - `.workflow/.trash/drift-realign-*` 保留历史 drift-realign 快照（如 `20260726T103000`、`20260728T090000`、`20260728T210000`），用于对齐/回滚审计。
- 该机制与 MAESTRO 的 `maestro spec supersede/conflict`、知识库 record 流程配合，确保"规则演化链"可追溯。

---

## 附录：跨切面关键文件索引

| 关注点 | 文件 |
|---|---|
| 异常层次 | `quantflow/common/exceptions.py`、`quantflow/common/__init__.py` |
| 事件总线 | `quantflow/common/event_bus.py`、`quantflow/common/models.py` |
| 配置 | `quantflow/common/config.py`、`quantflow/config/default.yaml` |
| 日志 | `quantflow/monitoring/logger.py` |
| 脱敏 | `quantflow/common/redaction.py` |
| URL 安全 | `quantflow/common/url_safety.py` |
| 指标 | `quantflow/monitoring/metrics.py` |
| 告警 | `quantflow/monitoring/alerts.py` |
| 可观测性接缝 | `quantflow/common/monitoring_sink.py` |
| 熔断 | `quantflow/execution/kill_switch.py` |
| Station 安全 | `quantflow/web/security.py`、`quantflow/web/app.py` |
| 数据安全 | `quantflow/data/feature_store.py`、`quantflow/data/cleaner.py`、`quantflow/data/mtf_aligner.py` |
| 前视扫描 | `quantflow/strategy/validation/lookahead.py` |
| 测试配置 | `pyproject.toml` |
| 状态/drift | `.workflow/state.json` |
