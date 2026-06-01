# 架构设计文档 (Architecture) — QuantFlow 量化交易系统

## 1. 架构总览

### 1.1 六层分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ L6: 监控与运维 (Observability)                                       │
│   Grafana Dashboard │ Prometheus Metrics │ AlertManager │ Telegram  │
├─────────────────────────────────────────────────────────────────────┤
│ L5: 交易执行 (Execution)                                             │
│   ExecutionEngine │ OKXGateway(CCXT) │ PaperGateway │ KillSwitch    │
│   OrderManager │ PositionManager │ Reconciliation                    │
├─────────────────────────────────────────────────────────────────────┤
│ L4: 信号与风控 (Signal & Risk)                                       │
│   SignalGenerator │ RiskEngine │ PositionSizer │ PortfolioManager   │
├─────────────────────────────────────────────────────────────────────┤
│ L3: 策略研发 (Research & Strategy)                                   │
│   ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│   │ VectorBT Engine  │  │ EventDriven Engine│  │ ValidationGate  │  │
│   │ (研究/优化)       │  │  (验证/实盘)自建  │  │ (CPCV/DSR/WFO) │  │
│   └──────────────────┘  └──────────────────┘  └─────────────────┘  │
├─────────────────────────────────────────────────────────────────────┤
│ L2: 指标与因子 (Indicators & Factors)                                │
│   IndicatorEngine │ FactorRegistry │ FeatureStore(DuckDB)           │
├─────────────────────────────────────────────────────────────────────┤
│ L1: 数据层 (Data)                                                    │
│   DataFetcher(CCXT) │ DataCleaner │ ParquetStore │ DuckDB │ Redis   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心设计原则

1. **层间单向依赖**：L1 → L2 → L3 → L4 → L5 → L6，低层不依赖高层
2. **接口驱动**：每层对外暴露接口（Protocol/ABC），内部实现可替换
3. **配置外置**：策略参数、风控阈值、API 凭证全部 YAML/ENV 配置
4. **事件解耦**：L4→L5 通过事件总线通信，策略不直接调用 Gateway
5. **回测-实盘一致**：策略代码不感知运行模式（backtest/paper/live）

---

## 2. 项目结构

```
quantflow/
├── config/                     # 配置文件
│   ├── default.yaml            # 默认配置
│   ├── strategies/             # 策略配置
│   └── risk.yaml               # 风控配置
│
├── data/                       # L1: 数据层
│   ├── __init__.py
│   ├── fetcher.py              # CCXT 数据获取
│   ├── cleaner.py              # 数据清洗
│   ├── store.py                # Parquet 存储 + DuckDB 查询
│   ├── feature_store.py        # Feature Store（研究+实盘一致）
│   └── redis_cache.py          # Redis 实时缓存
│
├── indicators/                 # L2: 指标与因子层
│   ├── __init__.py
│   ├── base.py                 # FactorBase 接口
│   ├── registry.py             # 因子注册表
│   ├── engine.py               # IndicatorEngine
│   ├── trend.py                # 趋势指标（MA/EMA/MACD）
│   ├── momentum.py             # 动量指标（RSI/Stochastic）
│   ├── volatility.py           # 波动指标（ATR/Bollinger/Keltner）
│   └── volume.py               # 成交量指标（OBV/VolumeRatio）
│
├── strategy/                   # L3: 策略研发层
│   ├── __init__.py
│   ├── base.py                 # StrategyBase 接口
│   ├── context.py              # StrategyContext
│   ├── templates/              # 策略模板
│   │   ├── trend_following.py
│   │   ├── mean_reversion.py
│   │   └── momentum.py
│   ├── research/               # VectorBT 研究引擎
│   │   ├── __init__.py
│   │   ├── backtest.py         # 向量化回测
│   │   ├── optimizer.py        # Optuna 参数优化
│   │   └── report.py           # 回测报告生成
│   ├── validation/             # 防过拟合验证
│   │   ├── __init__.py
│   │   ├── cpcv.py             # Combinatorial Purged CV
│   │   ├── dsr.py              # Deflated Sharpe Ratio
│   │   ├── pbo.py              # Probability of Backtest Overfitting
│   │   ├── wfo.py              # Walk-Forward Optimization
│   │   └── gate.py             # GO/NO-GO 决策门
│   └── engine.py               # TradingSession 事件驱动引擎
│
├── signal/                     # L4: 信号与风控层
│   ├── __init__.py
│   ├── generator.py            # SignalGenerator
│   ├── risk_engine.py          # RiskEngine（风控检查）
│   ├── position_sizer.py       # PositionSizer（Kelly/VaR）
│   ├── portfolio.py            # PortfolioManager（组合管理）
│   └── risk_metrics.py         # VaR/CVaR/Drawdown 计算
│
├── execution/                  # L5: 交易执行层
│   ├── __init__.py
│   ├── engine.py               # ExecutionEngine
│   ├── gateway_base.py         # GatewayBase 接口
│   ├── okx_gateway.py          # OKX Gateway (CCXT)
│   ├── paper_gateway.py        # PaperTrade Gateway
│   ├── order_manager.py        # OrderManager
│   ├── position_manager.py     # PositionManager
│   └── kill_switch.py          # KillSwitch
│
├── monitoring/                 # L6: 监控与运维层
│   ├── __init__.py
│   ├── metrics.py              # Prometheus 指标定义
│   ├── alerts.py               # 告警（Telegram/LINE）
│   └── logger.py               # 结构化日志
│
├── common/                     # 公共模块
│   ├── __init__.py
│   ├── models.py               # 数据模型（Bar/Tick/Order/Signal）
│   ├── event_bus.py            # 事件总线
│   ├── config.py               # 配置管理
│   └── exceptions.py           # 自定义异常
│
├── cli/                        # 命令行界面
│   ├── __init__.py
│   └── main.py                 # CLI 入口（Typer）
│
├── tests/                      # 测试
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
├── docker/                     # Docker 配置
│   ├── Dockerfile
│   └── docker-compose.yaml
│
├── pyproject.toml              # 项目配置
└── README.md
```

---

## 3. 核心模块详细设计

### 3.1 事件总线 (EventBus)

系统核心通信机制，L4→L5 解耦的关键：

```python
# common/event_bus.py
class EventBus:
    """发布-订阅事件总线，线程安全"""

    def subscribe(self, event_type: str, handler: Callable) -> None: ...
    def unsubscribe(self, event_type: str, handler: Callable) -> None: ...
    def publish(self, event: Event) -> None: ...

# 核心事件类型
EVENT_BAR = "event.bar"           # K线更新
EVENT_TICK = "event.tick"         # Tick 更新
EVENT_SIGNAL = "event.signal"     # 策略信号
EVENT_ORDER = "event.order"       # 订单状态变更
EVENT_TRADE = "event.trade"       # 成交回报
EVENT_RISK = "event.risk"         # 风控事件
```

### 3.2 数据流架构

```
OKX WebSocket ──→ Redis Cache ──→ EventBus(BAR) ──→ Strategy.on_bar()
                                       ↓                    ↓
                               SignalGenerator ←── Strategy 信号
                                       ↓
                                  RiskEngine.check()
                                       ↓
                                 PositionSizer.size()
                                       ↓
                              ExecutionEngine.submit()
                                       ↓
                              OKXGateway.send_order()
                                       ↓
                              EventBus(ORDER/TRADE)
                                       ↓
                              PositionManager.update()
                                       ↓
                              Prometheus + Grafana
```

### 3.3 回测模式 vs 实盘模式

```python
# 同一策略代码，不同运行模式
class TradingSession:
    """统一交易会话，管理运行模式"""

    def __init__(self, mode: Literal["backtest", "paper", "live"]):
        self.mode = mode
        self.gateway = self._create_gateway(mode)
        self.engine = self._create_engine(mode)

    def _create_gateway(self, mode):
        return {
            "backtest": BacktestGateway,   # 从 Parquet 重放
            "paper": PaperGateway,          # 本地模拟交易
            "live": OKXGateway,             # CCXT + OKX
        }[mode]

    def _create_engine(self, mode):
        return {
            "backtest": VectorBTEngine,     # 向量化回测引擎
            "paper": EventDrivenEngine,     # 自建事件驱动引擎
            "live": EventDrivenEngine,      # 自建事件驱动引擎
        }[mode]
```

### 3.4 防过拟合验证管道

```
策略参数候选
     ↓
[Step 1] VectorBT 向量化快速筛选
     │  → 保留 Top 10 (Sharpe 排序)
     ↓
[Step 2] Optuna 贝叶斯精调
     │  → 保留 Top 3
     ↓
[Step 3] 事件驱动模拟引擎
     │  → 确认真实滑点/手续费下可行
     ↓
[Step 4] CPCV 多路径验证 (purgedcv)
     │  → PBO < 0.5 ? 继续 : 淘汰
     ↓
[Step 5] DSR 统计修正
     │  → DSR > 0.95 ? 继续 : 淘汰
     ↓
[Step 6] Walk-Forward GO/NO-GO
     │  → OOS Efficiency > 50% ? GO : NO-GO
     ↓
[GO] → 进入 PaperTrade
[NO-GO] → 返回 Step 1 重新探索
```

### 3.5 Feature Store 设计

```python
# data/feature_store.py
class FeatureStore:
    """研究+实盘一致性特征存储"""

    def __init__(self, duckdb_path: str, parquet_dir: str):
        self.db = duckdb.connect(duckdb_path)
        self.parquet_dir = parquet_dir

    def compute_features(self, symbol: str, timestamp: int,
                         indicators: list[str]) -> pd.DataFrame:
        """计算指定时间点的特征（时间点安全，无未来数据泄漏）"""
        # 只使用 timestamp 之前的数据
        raw = self._load_raw_up_to(symbol, timestamp)
        features = self._compute(raw, indicators)
        return features

    def save_features(self, symbol: str, features: pd.DataFrame) -> None:
        """持久化特征到 Parquet"""
        # 写入 symbol/year/month 分区的 Parquet
        ...

    def load_features(self, symbol: str, start: int, end: int) -> pd.DataFrame:
        """加载历史特征（回测用）"""
        return self.db.execute(f"""
            SELECT * FROM read_parquet('{self.parquet_dir}/{symbol}/*/*/*.parquet')
            WHERE timestamp BETWEEN {start} AND {end}
            ORDER BY timestamp
        """).df()
```

---

## 4. Gateway 抽象设计

### 4.1 OKX Gateway (CCXT)

```python
class OKXGateway(GatewayBase):
    """OKX 交易所 Gateway，基于 CCXT"""

    def __init__(self, config: OKXConfig):
        self.exchange = ccxt.okx({
            'apiKey': config.api_key,
            'secret': config.secret,
            'password': config.passphrase,
            'sandbox': config.sandbox,  # 模拟盘用 sandbox 模式
        })
        self.ws = None  # WebSocket 连接

    async def connect(self) -> None:
        await self.exchange.load_markets()
        self.ws = OKXWebSocket(config)  # 行情 WebSocket

    async def subscribe(self, symbols: list[str]) -> None:
        await self.ws.subscribe(symbols, channels=['ticker', 'trades'])

    async def send_order(self, order: OrderRequest) -> str:
        result = await self.exchange.create_order(
            symbol=order.symbol,
            type=order.order_type,
            side=order.side,
            amount=order.quantity,
            price=order.price,
        )
        return result['id']

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        await self.exchange.cancel_order(order_id, symbol)
        return True

    async def query_position(self) -> list[Position]:
        positions = await self.exchange.fetch_positions()
        return [self._parse_position(p) for p in positions]

    async def disconnect(self) -> None:
        await self.exchange.close()
        if self.ws:
            await self.ws.close()
```

### 4.2 Paper Gateway

```python
class PaperGateway(GatewayBase):
    """本地模拟交易 Gateway"""

    def __init__(self, config: PaperConfig):
        self.cash = config.initial_capital
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}
        self.fee_rate = config.fee_rate  # 默认 0.001 (0.1%)

    async def send_order(self, order: OrderRequest) -> str:
        order_id = str(uuid4())
        # 模拟撮合：按当前市价成交
        fill_price = order.price or self._get_market_price(order.symbol)
        fill_qty = order.quantity
        fee = fill_price * fill_qty * self.fee_rate
        # 更新持仓和资金
        self._execute_fill(order_id, order, fill_price, fill_qty, fee)
        return order_id
```

---

## 5. 风控引擎设计

### 5.1 风控检查管道

```python
class RiskEngine:
    """多层风控检查"""

    def check(self, signal: Signal, portfolio: Portfolio) -> RiskDecision:
        checks = [
            self._check_position_limit,     # 单标的仓位上限
            self._check_portfolio_limit,     # 组合持仓数量上限
            self._check_daily_loss,          # 日度亏损限制
            self._check_drawdown,            # 最大回撤限制
            self._check_correlation,         # 策略相关度
            self._check_liquidity,           # 流动性检查
        ]
        for check in checks:
            result = check(signal, portfolio)
            if not result.passed:
                return result
        return RiskDecision(passed=True)

    def _check_drawdown(self, signal, portfolio) -> RiskDecision:
        dd = portfolio.current_drawdown
        if dd > self.config.max_drawdown:  # 默认 -10%
            self.event_bus.publish(Event(EVENT_RISK, {
                "type": "drawdown_breach",
                "value": dd,
                "limit": self.config.max_drawdown,
            }))
            return RiskDecision(passed=False, reason="drawdown_breach")
        return RiskDecision(passed=True)
```

### 5.2 Kill Switch

```python
class KillSwitch:
    """紧急停止机制"""

    def activate(self, reason: str) -> None:
        """一键清仓+停止所有策略"""
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")
        # 1. 停止所有策略
        self.strategy_manager.stop_all()
        # 2. 撤销所有挂单
        self.order_manager.cancel_all()
        # 3. 市价平仓所有持仓
        for symbol, pos in self.position_manager.get_all():
            side = 'sell' if pos.quantity > 0 else 'buy'
            self.execution_engine.submit(OrderRequest(
                symbol=symbol, side=side,
                order_type='market', quantity=abs(pos.quantity),
            ))
        # 4. 发送紧急告警
        self.alert_manager.send_critical(f"KILL SWITCH: {reason}")
```

---

## 6. 配置管理

### 6.1 配置层次

```yaml
# config/default.yaml
data:
  parquet_dir: "./data/parquet"
  duckdb_path: "./data/quantflow.duckdb"
  redis_url: "redis://localhost:6379"
  fetcher:
    exchange: "okx"
    sandbox: false
    rate_limit: 10  # requests per second

indicators:
  default_params:
    rsi_period: 14
    macd_fast: 12
    macd_slow: 26
    macd_signal: 9
    atr_period: 14
    bollinger_period: 20
    bollinger_std: 2

strategy:
  research_engine: "vectorbt"  # vectorbt | eventdriven
  validation:
    cpcv_groups: 8
    cpcv_test_groups: 2
    embargo_periods: 5
    dsr_threshold: 0.95
    pbo_threshold: 0.5
    wfo_oos_efficiency: 0.5

risk:
  position_limit_pct: 0.20       # 单标的最大仓位 20%
  max_positions: 5                # 最大持仓数
  daily_loss_limit: -0.03         # 日度最大亏损 -3%
  weekly_loss_limit: -0.05        # 周度最大亏损 -5%
  max_drawdown: -0.10             # 最大回撤 -10%
  kill_switch_enabled: true

execution:
  mode: "paper"  # backtest | paper | live
  order_timeout: 30               # 订单超时秒数
  reconnect_interval: 5           # 断线重连间隔秒数

monitoring:
  prometheus_port: 9090
  grafana_port: 3000
  alert_channels:
    - type: "telegram"
      chat_id: "${TELEGRAM_CHAT_ID}"
      token: "${TELEGRAM_BOT_TOKEN}"
```

---

## 7. 部署架构

### 7.1 Docker Compose

```yaml
# docker/docker-compose.yaml
services:
  quantflow:
    build: ..
    volumes:
      - ../data:/app/data
      - ../config:/app/config
    env_file: ../.env
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ../config/prometheus.yml:/etc/prometheus/prometheus.yml

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana

volumes:
  redis_data:
  grafana_data:
```

### 7.2 运行模式

```bash
# Phase 1: 命令行回测
python -m quantflow.cli research \
  --strategy trend_following \
  --symbol BTC/USDT \
  --start 2024-01-01 --end 2025-01-01

# Phase 1: 参数优化
python -m quantflow.cli optimize \
  --strategy trend_following \
  --symbol BTC/USDT \
  --method bayesian --trials 200

# Phase 2: 防过拟合验证
python -m quantflow.cli validate \
  --strategy trend_following \
  --method cpcv --groups 8 --test-groups 2

# Phase 2: 模拟盘
python -m quantflow.cli run --mode paper --strategy trend_following

# Phase 3: 实盘
python -m quantflow.cli run --mode live --strategy trend_following
```

---

## 8. 技术栈版本锁定

| 组件 | 版本 | 理由 |
|------|------|------|
| Python | 3.11+ | 性能优化 + 类型提示完善 |
| CCXT | 4.x | OKX API 支持 + async |
| VectorBT | 0.26+ | 向量化回测 + Portfolio |
| EventDriven Engine | 自建 | 事件驱动 + 统一运行模式 |
| Optuna | 3.6+ | 贝叶斯优化 + GPSampler |
| purgedcv | 0.0.10+ | CPCV + DSR |
| pandas-ta | 0.3+ | 130+ 技术指标 |
| TA-Lib | 0.4+ | C 层高性能指标 |
| DuckDB | 1.1+ | 嵌入式 OLAP + Parquet |
| Redis | 7.x | 实时缓存 |
| Grafana | 11+ | 可视化 |
| Prometheus | 2.x | 指标收集 |
| Docker | 24+ | 容器化 |
| Typer | 0.12+ | CLI 框架 |
| Pydantic | 2.x | 数据验证 + 配置管理 |

---

## 9. 扩展路径

### 9.1 A 股支持（Phase 4 扩展）
- 新增 `MiniQMTGateway` 实现 `GatewayBase`
- 数据源切换：AKShare + xtdata 替代 CCXT
- 交易时间适配：A 股交易时段（9:30-15:00）
- T+1 限制适配

### 9.2 AI 因子增强（Phase 3）
- 新增 `qlib/` 模块，集成 RD-Agent
- 新增 `sentiment/` 模块，集成 FinBERT
- Feature Store 新增 AI 因子列
- 模型版本管理（MLflow）

### 9.3 Delta Lake 升级（Phase 3 可选）
- Parquet → Delta Lake 格式迁移
- ACID 事务支持
- Time-travel 查询
- Schema evolution