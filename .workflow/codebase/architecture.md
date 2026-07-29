# QuantFlow 架构文档

> Mapper 2 (Architecture) 产出 · 基于 `quantflow/` 实际源码分析
> 个人 Crypto 量化交易系统（OKX），六层架构：L1 数据 → L2 指标因子 → L3 策略研发 → L4 信号风控 → L5 交易执行 → L6 监控运维 + Common 公共层 + Web Station + CLI

## 1. 分层架构图

```
                          ┌──────────────────────────────────────────────┐
                          │  CLI (quantflow.cli.main:app) — Typer/Rich   │  入口
                          │  Web (quantflow.web.app:create_app) — aiohttp │  入口
                          └───────────────┬──────────────────┬───────────┘
                                          │                  │
                          ┌───────────────▼──────────────────▼───────────┐
   L6 监控运维            │ monitoring/  metrics · alerts · logger · sink  │  Prometheus/Grafana/Telegram
                          └───────────────┬──────────────────┬───────────┘
                                          │ (MonitoringSink 协议注入, 不反向依赖)
   L5 交易执行            ┌───────────────▼──────────────────▼───────────┐
                          │ execution/  GatewayBase · OKX/Paper · Engine  │  OrderRouter · OrderManager
                          │   · PositionManager · KillSwitch              │  OrderManager · KillSwitch
                          └───────────────┬──────────────────┬───────────┘
   L4 信号风控            ┌───────────────▼──────────────────▼───────────┐
                          │ signal/  generator · risk_engine · sizer     │  portfolio · risk_metrics
                          └───────────────┬──────────────────┬───────────┘
   L3 策略研发            ┌───────────────▼──────────────────▼───────────┐
                          │ strategy/  base · engine(TradingSession)      │  research/ · validation/
                          │   · templates/ · ai_factors · sentiment ·     │  rd_agent
                          └───────────────┬──────────────────┬───────────┘
   L2 指标因子            ┌───────────────▼──────────────────▼───────────┐
                          │ indicators/  FactorBase · FactorRegistry      │  IndicatorEngine · regime
                          │   · elliott_wave · trend/momentum/vol/volume │
                          └───────────────┬──────────────────┬───────────┘
   L1 数据                ┌───────────────▼──────────────────▼───────────┐
                          │ data/  fetcher · cleaner · store             │  feature_store · redis_cache
                          │   · mtf_aligner                              │  MTFAligner
                          └───────────────┬──────────────────┬───────────┘
                          ┌───────────────▼──────────────────▼───────────┐
   Common 公共层          │ common/  models · event_bus · config ·        │  所有层共享, 不被业务层反向依赖
                          │   exceptions · monitoring_sink · validators   │
                          └──────────────────────────────────────────────┘
```

### 各层一句话职责

| 层 | 模块 | 职责 |
|----|------|------|
| **L1 数据** | `data/fetcher.py` | CCXT 拉取/WebSocket 实时行情（REST 轮询 + WS，30s 调用超时） |
| | `data/cleaner.py` | OHLCV 清洗、缺失/异常值处理 |
| | `data/store.py` | Parquet 分区存储 + DuckDB 零导入查询（`DataStore`） |
| | `data/feature_store.py` | 时间点安全特征计算/存储，研究+实盘特征一致（`FeatureStore`） |
| | `data/redis_cache.py` | 实时行情 Redis 缓存（`RedisCache`，60s TTL） |
| | `data/mtf_aligner.py` | 多周期（1W/4H/1H/15m）数据对齐（`MTFAligner`） |
| **L2 指标因子** | `indicators/base.py` | `FactorBase` 抽象 + `FactorRegistry` 注册表 |
| | `indicators/engine.py` | `IndicatorEngine` 批量计算 27 因子（trend7+momentum4+vol5+volume5+wave6） |
| | `indicators/regime.py` | `MarketRegimeDetector`（ADX + 波动率）做策略宏观闸门 |
| | `indicators/elliott_wave.py` 等 | Elliott Wave、ZigZag、Fibonacci、Divergence 等波浪因子 |
| **L3 策略研发** | `strategy/base.py` | `StrategyBase` 抽象 + `StrategyContext` |
| | `strategy/engine.py` | `TradingSession`——统一 backtest/paper/live 编排引擎 |
| | `strategy/research/` | `BacktestEngine`（纯 pandas 回测）、`StrategyOptimizer`（Optuna）、`report` |
| | `strategy/validation/` | CPCV / DSR / PBO / WFO / lookahead / monte_carlo / GO-NO-GO `gate` |
| | `strategy/templates/` | 7 个内置模板策略（trend_following/mean_reversion/elliott_wave/volatility_breakout/funding_rate/momentum_rotation/ml_ensemble） |
| | `strategy/ai_factors` · `sentiment` · `rd_agent` | AI 因子、情绪分析、RD-Agent 自动策略发现 |
| | `strategy/catalog.py` | 策略工厂/规格共享目录，CLI 与 Web 共用 |
| **L4 信号风控** | `signal/generator.py` | `SignalGenerator` 信号生成 + 同标的多策略强度加权合并（consolidate） |
| | `signal/risk_engine.py` | `RiskEngine` 7 项短路风控检查（仓位/组合/预算/日损/周损/回撤/VaR-CVaR） |
| | `signal/position_sizer.py` | `PositionSizer` 半 Kelly + 波动率目标 + 单名上限 |
| | `signal/portfolio.py` | `PortfolioManager` 持仓记账、盯市、回撤跟踪（L4 为权威账本） |
| | `signal/risk_metrics.py` | VaR/CVaR/回撤等统计（单一公式归属，防重复实现） |
| **L5 交易执行** | `execution/gateway_base.py` | `GatewayBase` 抽象（connect/send_order/cancel_order/query_positions） + `GatewayError` |
| | `execution/okx_gateway.py` · `paper_gateway.py` | OKX 实盘 / 模拟盘实现 |
| | `execution/engine.py` | `ExecutionEngine` 订单编排（闸刀→路由→跟踪→事件→成交） |
| | `execution/order_router.py` | `OrderRouter` 网关派发 + Order 构造（从 Engine 拆出） |
| | `execution/order_manager.py` | `OrderManager` 订单状态机 + 超时看门狗 |
| | `execution/position_manager.py` | `PositionManager` L4 的薄委托层 |
| | `execution/kill_switch.py` | `KillSwitch` 紧急熔断（fail-closed） |
| **L6 监控运维** | `monitoring/metrics.py` | Prometheus Counter/Gauge/Histogram + 指标服务器 |
| | `monitoring/alerts.py` | `AlertManager`（Telegram/LINE/Webhook），密文脱敏 |
| | `monitoring/logger.py` | 日志初始化 |
| | `monitoring/sink.py` | `DefaultMonitoringSink`——`MonitoringSink` 协议的 L6 实现 |
| **Common** | `common/models.py` | `Bar`/`Signal`/`Order`/`Position`/`Portfolio`/`RiskDecision` 等数据模型 + 事件类型常量 |
| | `common/event_bus.py` | `EventBus` 发布-订阅（同步/异步处理器） |
| | `common/config.py` | `AppConfig`（Pydantic），优先级 CLI > ENV(`QUANTFLOW_*`) > YAML |
| | `common/monitoring_sink.py` | `MonitoringSink` Protocol + `NullMonitoringSink`（零观测默认实现） |
| | `common/exceptions.py` · `validators.py` · `redaction.py` · `url_safety.py` | 异常/校验/密文脱敏/出站 URL 校验 |
| **Web** | `web/app.py` · `service.py` · `session_manager.py` · `security.py` · `rate_limit.py` · `history.py` | aiohttp QuantFlow Station（23 REST 端点，含鉴权/CSRF/限流/路径脱敏） |
| **CLI** | `cli/main.py` | Typer/Rich 入口（`download`→`research`→`optimize`→`validate`→`run`→`status`） |

## 2. 模块边界与依赖方向

### 2.1 单向依赖（低层不依赖高层）
依赖方向严格自上而下：`Web/CLI → L5 → L4 → L3 → L2 → L1`，全部汇聚到 `common/`。

- 低层（`data`/`indicators`/`common`）**不 import 任何业务高层**。例如 `data/store.py` 仅依赖 `common.exceptions`/`common.validators`；`indicators/engine.py` 仅依赖同层 `trend/momentum/volatility/volume` 与 `common`。
- L5 `execution` 依赖 `signal` 仅通过类型注解（`TYPE_CHECKING`）：`execution/engine.py:30` `from quantflow.signal.portfolio import PortfolioManager` 在 `TYPE_CHECKING` 块内，运行期通过构造注入 `set_portfolio()`，避免 L5→L4 硬耦合。`execution/engine.py:74` 从配置选择 `PaperGateway`/`OKXGateway`，二者均只实现 `GatewayBase`。
- L3 `strategy/engine.py` 依赖 L4/L5 **类**（`ExecutionEngine`/`RiskEngine`/`PositionSizer`/`PortfolioManager`/`KillSwitch`），但**不依赖 L6**：观测通过 `common.monitoring_sink.MonitoringSink` 协议，具体 sink 由调用方注入（`strategy/engine.py:19,105`）。

### 2.2 接口驱动（Protocol / ABC）
- **GatewayBase**（`execution/gateway_base.py`，ABC）：`connect`/`send_order`/`cancel_order`/`query_positions` 抽象；`disconnect`/`cancel_all_orders`/`update_market_price`/`subscribe` 提供默认实现。OKX 与 Paper 可互换。
- **StrategyBase**（`strategy/base.py`，ABC）：`on_init`/`on_bar`/`on_tick`/`generate_signals` 为策略契约。
- **FactorBase**（`indicators/base.py`，ABC）：`compute(df, **params)`，`FactorRegistry` 全局注册表（`indicators/engine.py:72` `registry = FactorRegistry()`）支持自动发现。
- **MonitoringSink**（`common/monitoring_sink.py`，`runtime_checkable` Protocol）：L3/L4/L5 只认这个协议，具体 `DefaultMonitoringSink`（`monitoring/sink.py`）由 `cli`/`session_manager` 注入（见 §6 决策）。
- **EventBus**（`common/event_bus.py`）：发布-订阅解耦，`subscribe`/`publish`/`publish_async`，异常被捕获记录防止级联失败。

### 2.3 配置外置（YAML / ENV）
- 全部配置经 `common/config.py` 的 `AppConfig`（Pydantic 模型），`load_config()` 优先级 **CLI 参数 > 环境变量(`QUANTFLOW_*__*`) > YAML 默认值**。
- API Key 仅从环境变量读取（`cli/main.py:_load_gateway_config_from_env` 校验 `OKX_API_KEY/OKX_SECRET/OKX_PASSPHRASE`；`web/session_manager.py:_gateway_config_from_env` 同源）。`.env` 不入库。
- Web 层对请求传入的 `config_path` 用 `resolve_config_path_safe()` 做目录遍历防护；`save_config()` 落盘前 `SENSITIVE_FIELDS` 脱敏。

## 3. 关键数据流

```
CCXT / WebSocket (L1 fetcher)
        │  fetch_ohlcv / watch
        ▼
RedisCache (L1)  ──缓存实时行情(60s TTL)
        │
        ▼  TradingSession.run_data_loop / _run_local_data_loop 构造 Bar
EventBus.publish(EVENT_BAR)  ── TradingSession.on_bar (strategy/engine.py:252)
        │
        ▼  MarketRegimeDetector.update() 闸门 (strategy/engine.py:342)
        ▼  for strategy: strategy.on_bar(ctx, bar) → ctx.emit_signal() (L3)
        ▼  SignalGenerator.consolidate_signals() 同标的合并 (L4 generator)
        │
        ▼  _process_signal():
        │    1) RiskEngine.check() 7 项短路风控 (L4 risk_engine)
        │    2) EventBus.publish(EVENT_SIGNAL)
        │    3) PositionSizer.size() 半 Kelly 仓位 (L4 sizer)
        │    4) ExecutionEngine.submit_order() (L5 engine)
        │         ├─ KillSwitch 闸门 (若激活则拒单)
        │         ├─ OrderRouter.route() → Gateway.send_order() (L5→Gateway)
        │         ├─ OrderManager 跟踪状态/超时 (L5)
        │         └─ fill 更新 L4 PortfolioManager 账本
        ▼
EventBus.publish(EVENT_ORDER / EVENT_FILL)
        │
        ▼  MonitoringSink (注入的 L6 DefaultMonitoringSink)
             ├─ Prometheus metrics (orders/signals/risk/portfolio/bar_latency)
             └─ AlertManager → Telegram / LINE / Webhook
        ▼
Grafana 看板 + 告警（L6 订阅侧，由 sink 实现而非低层 import）
```

要点：`TradingSession.on_bar`（`strategy/engine.py:242`）是唯一编排入口，把 L1 进来的 Bar 流过 L3→L4→L5，再通过注入的 `MonitoringSink` 把可观测性副作用推给 L6，全程**低层不反向 import 高层**。

## 4. 入口点（Entry Points）

- **CLI**：`quantflow.cli.main:app`（`typer.Typer`）。命令链：`download` → `research` → `optimize` → `validate` → `run` → `status`。`setup_logging()` 在导入期执行；`__version__` 来自 `quantflow/__init__.py`。策略工厂经 `strategy/catalog.py` 共享。
- **Web Station**：`quantflow.web.app:create_app`（`aiohttp.web`）。`create_app()` 注册 23 个路由（含 `/`、`/static/`、`/api/overview`、`/api/strategies`、`/api/data*`、`/api/research*`、`/api/validate*`、`/api/workbench/state`、`/api/monitoring`、`/api/execution`、`/api/session*`）。服务由 `StationService`（业务编排）与 `StationSessionManager`（后台 `TradingSession` 生命周期）支撑，二者经 `web.AppKey` 注入 `app`。`web.run_app(create_app(), ...)` 为启动钩子。

## 5. 核心接口与契约

### 5.1 StrategyBase（`strategy/base.py`）
```python
class StrategyBase(ABC):
    def on_init(self, ctx: StrategyContext) -> None          # 初始化(设置指标)
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None  # 事件驱动路径(实盘/模拟)
    def on_tick(self, ctx: StrategyContext, tick: Any) -> None# 实时 tick(默认空)
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]  # 向量化(回测)
```
注：`generate_signals`（无状态研究）与 `on_bar`（有状态实盘）是**尽力对齐而非严格保证**——regime 闸门只在 `on_bar` 生效，故回测交易集合是实盘的超集（ISS-20260720-001，设计属性）。

### 5.2 GatewayBase（`execution/gateway_base.py`）
```python
class GatewayBase(ABC):
    @abstractmethod async def connect(self, config: dict | None = None) -> None
    @abstractmethod async def send_order(self, order: Order) -> str          # 返回交易所订单 id
    @abstractmethod async def cancel_order(self, order_id: str, symbol: str) -> bool
    @abstractmethod async def query_positions(self) -> list[Position]        # 失败须抛 GatewayError，不可返 []
```
`query_positions` 失败必须抛 `GatewayError`（而非返回空列表），以保证 KillSwitch 等 fail-closed 调用方不会误判为"无持仓"。

### 5.3 FactorBase（`indicators/base.py`）
```python
class FactorBase(ABC):
    name: str = ""
    dependencies: ClassVar[list[str]] = []
    @abstractmethod
    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series
```
全局 `registry` 单例；`FactorRegistry.register/get/compute` 支持按名发现与计算。

### 5.4 EventBus（`common/event_bus.py`）
```python
class EventBus:
    def subscribe(self, event_type: str, handler: Callable[[Event], Any]) -> None
    def publish(self, event: Event) -> None          # 同步; 异步处理器调度为 task
    async def publish_async(self, event: Event) -> None  # 同步等待所有(含异步)处理器
```
六类核心事件常量（`common/models.py`）：`EVENT_BAR / EVENT_TICK / EVENT_SIGNAL / EVENT_ORDER / EVENT_FILL / EVENT_RISK`。

## 6. 值得注意的架构决策

1. **自建 `TradingSession` 而非外部回测引擎**
   L3 `strategy/engine.py:TradingSession` 自研事件驱动引擎，统一编排 backtest/paper/live 三种模式、复用同一套策略与风控代码。回测侧 `research/backtest.py:BacktestEngine` 已从 VectorBT **迁移到纯 pandas/numpy 实现**（注释明确：VectorBT 需 numba、不兼容 Python 3.14+）。自研带来回测-实盘一致性，但需自行维护 `on_bar`/`generate_signals` 两条路径的对齐（见 §5.1 注）。

2. **`MonitoringSink` Protocol 注入，杜绝 L3/L4/L5 → L6 反向依赖**
   `common/monitoring_sink.py` 定义协议 + `NullMonitoringSink` 零观测默认实现；L6 `monitoring/sink.py:DefaultMonitoringSink` 才真正接 Prometheus/AlertManager。低层只 `self._sink.record_*/send_alert`，具体 sink 由 `cli`/`session_manager` 通过 `create_default_sink(config)` 注入（`strategy/engine.py:105`、`execution/engine.py:81`、`signal/risk_engine.py:37`、`execution/kill_switch.py:43`）。
   - 动机：历史上 `strategy/engine.py` 直接 import `monitoring.metrics`/`monitoring.alerts`，形成 L3→L6 耦合，且某些指标用惰性 import 藏匿、绕过顶层 grep 审计（"audit-evasion"）。协议化后观测成为单一审计面，低层编译期不再依赖 L6（ISS-019 / ISS-20260724-044）。
   - 区分 `EventBus`（控制流，BAR/SIGNAL/ORDER/FILL/RISK）与 `MonitoringSink`（可观测性副作用）——不新增遥测事件污染事件契约。

3. **`ExecutionEngine` 上帝对象拆分出 `OrderRouter`**
   `execution/engine.py` 原先承担 7 项职责（路由/订单状态/事件发布/指标/Order 构造/close/同步）。ISS-20260723-003 将"网关派发 + Order 构造"抽离到 `execution/order_router.py:OrderRouter`，`ExecutionEngine` 退化为薄编排层（闸刀 → `route()` → `OrderManager` 跟踪 → 指标 → 事件 → fill 处理）。
   - 生命周期采用 arch-017 **惰性绑定**模式：`ExecutionEngine`/`OrderRouter` 构造时网关尚不存在（`start()` 才建），故网关以 `None` 接受、`set_gateway()` 在 `start()` 后重绑；与 `set_portfolio()` 同构。

4. **L4 `PortfolioManager` 为权威账本，L5 `PositionManager` 仅作薄委托**
   `execution/position_manager.py` 委托到注入的 `PortfolioManager`（`execution/engine.py:74,97 set_portfolio`）。`TradingSession` 先建 Engine 再建 Portfolio，通过 `set_portfolio()` 把 L5 的 PositionManager 重绑到共享 L4 账本，保证 fill 更新与风控读到的同一份持仓（ISS-20260720-004 Wave 2）。`check_health()`/`snapshot_state()` 的持仓数也统一读 L4，避免 L4/L5 分歧。

5. **`KillSwitch` fail-closed（失败即锁）**
   `execution/kill_switch.py`：激活时取消挂单→市价平多/空→阻止新单。`query_positions` 抛 `GatewayError` 时**不**返回"成功+空列表"，而报 `status="failed"`，防止真实持仓仍开在交易所而误判已平仓（SEC-H5/REL-H8）。实盘模式强制 `kill_switch_enabled=True`，否则 `TradingSession.start` 拒绝启动（`strategy/engine.py:185`）。

6. **防过拟合验证管道前置为架构一级模块**
   `strategy/validation/`（cpcv/dsr/pbo/wfo/lookahead/monte_carlo/signal_quality/barriers）由 `gate.validation_gate()` 串成 GO/NO-GO 流水线（CPCV PBO<0.5 → DSR>0.95 → WFO OOS>50%）。`data/feature_store.py` 的时间点安全查询与 `strategy/validation/lookahead.py` 共同防止未来数据泄漏。

7. **Web 层安全边界内聚于 `web/security.py`**
   Station 鉴权/CSRF/loopback 校验/路径遍历防护集中到 `security.py`（REV-013），被任意入口复用；请求体上限 256 KiB（ISS-001），响应层 `_redact_paths()` 剥离 `parquet_dir/duckdb_path/config_path/redis_url` 等内部路径（ISS-036/CWE-200），错误统一经 `_error_response()` 调用 `redact_secrets` 脱敏（ISS-002/004）。

8. **配置单一真相源（single-source-of-truth）**
   多项原硬编码数值（half-Kelly `kelly_fraction`、VaR 置信度 `var_confidence`、仓位 `fixed_pct`/`min_order_notional`、手续费 `taker_fee`）已上提到 `AppConfig`，消除"YAML 值被静默丢弃"的 schema-drift（如 `config.py:46,64` 注释所示）。

---
*分析依据：`quantflow/` 下全部 `.py` 源码（含 `common/`、`data/`、`indicators/`、`strategy/`、`signal/`、`execution/`、`monitoring/`、`web/`、`cli/`）。未修改任何源文件。*
