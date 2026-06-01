# 产品需求文档 (PRD) — QuantFlow 量化交易系统

## 1. 概述

### 1.1 产品愿景
构建一个面向个人开发者的 Crypto 量化交易系统，覆盖从策略研究到实盘执行的完整闭环，以前沿防过拟合体系确保策略可靠性。

### 1.2 目标用户画像
- 常驻日本的个人量化开发者
- 主要使用 OKX 交易所
- 具备 Python 开发能力，偏好开源方案和 AI 辅助开发
- 追求"可运行、可验证、可维护、可迭代"而非高频或机构级

### 1.3 核心原则
1. **验证优先**：任何策略必须通过防过拟合验证才能进入实盘
2. **架构先行**：六层分层架构，接口定义清晰，模块独立迭代
3. **研究-实盘一致**：Feature Store 确保研究环境与实盘使用相同数据/特征
4. **渐进式复杂度**：Phase 1 命令行 MVP → Phase 2 Web UI + 模拟盘 → Phase 3 实盘 + AI

---

## 2. 功能需求

### 2.1 L1 数据层

#### FR-1.1 历史数据获取
- 通过 CCXT 获取 Crypto 历史 K线数据（1m/5m/15m/1h/4h/1d）
- 支持多交易对（BTC/USDT, ETH/USDT 等）
- 增量更新：每日自动拉取新数据，避免重复下载
- 数据去重和缺失检测

#### FR-1.2 实时行情接入
- 通过 CCXT WebSocket 接收 OKX 实时行情
- 支持 Ticker + OrderBook + Trade 三种数据流
- 本地 Redis 缓存最新行情

#### FR-1.3 数据清洗与存储
- 自动检测缺失 K线并标记
- 异常值过滤（价格偏离 > 5σ）
- 存储格式：Parquet (Hive 分区: symbol/year/month)
- DuckDB 查询层：零导入直接查询 Parquet

#### FR-1.4 Feature Store
- 统一特征计算管道，研究+实盘共享
- 特征版本管理：每次计算结果带时间戳和参数哈希
- 支持特征回溯：给定时间点返回该时刻可用特征

### 2.2 L2 指标与因子层

#### FR-2.1 技术指标计算
- 均线系列：SMA/EMA/DEMA（周期 5/10/20/60/120）
- 动量指标：RSI(14), MACD(12,26,9), Stochastic(14,3)
- 波动指标：ATR(14), Bollinger Bands(20,2), Keltner Channel
- 成交量指标：OBV, Volume SMA, Volume Ratio
- 使用 pandas-ta 为默认，TA-Lib 高性能场景可选

#### FR-2.2 自定义因子接口
- 标准化因子接口：`compute(df, params) -> Series`
- 因子注册表：自动发现并注册所有因子
- 因子依赖管理：因子 A 依赖因子 B 时自动计算

#### FR-2.3 因子评价（Phase 3）
- IC 值计算和排序
- IC_IR 评估（IC 均值/IC 标准差）
- 因子衰减分析
- RD-Agent 自动因子挖掘

### 2.3 L3 策略研发层

#### FR-3.1 VectorBT 研究引擎
- 向量化回测：单次回测 <1s（1年日线数据）
- 参数网格搜索：10000+ 参数组合 <30s
- 多策略对比面板
- 回测报告：收益曲线、回撤、Sharpe、Sortino、Calmar

#### FR-3.2 Optuna 参数优化
- GPSampler 贝叶斯优化（默认）
- CmaEsSampler 进化策略（连续参数）
- 多目标优化：同时优化 Sharpe + 最大回撤
- 优化过程可视化

#### FR-3.3 事件驱动验证引擎
- 基于自建 TradingSession 统一架构，回测与实盘共享同一事件驱动引擎
- 真实滑点模拟（按成交量比例）
- 手续费精确计算（Maker/Taker 分开）
- 涨跌停/交易暂停模拟
- 回测-实盘代码完全一致：通过 TradingSession 统一调度，确保验证环境与实盘行为一致

#### FR-3.4 防过拟合验证体系
- **CPCV（Combinatorial Purged Cross-Validation）**
  - 可配置组数和测试组数（默认 8 组 × 2 测试 = 28 路径）
  - Embargo 期消除信息泄漏
- **DSR（Deflated Sharpe Ratio）**
  - 修正多次测试偏差
  - DSR > 0.95 通过阈值
- **PBO（Probability of Backtest Overfitting）**
  - PBO < 0.5 通过阈值
  - 量化策略过拟合概率
- **Walk-Forward Optimization**
  - Anchored + Rolling 两种模式
  - OOS Efficiency > 50% 通过阈值
  - GO/NO-GO 决策门
- **Triple-Barrier Method**
  - 价格路径标注替代固定时间窗口
- **Minimum Track Record Length**
  - 计算实盘验证所需最短时间

#### FR-3.5 策略模板
- 趋势跟踪模板（MA交叉 + MACD确认）
- 均值回归模板（RSI超买超卖 + Bollinger带）
- 动量模板（相对强弱 + 行业轮动）
- 自定义策略模板（继承基类，实现 on_bar/on_tick）

### 2.4 L4 信号与风控层

#### FR-4.1 信号生成
- 标准化信号格式：`{symbol, direction, strength, timestamp, strategy_id}`
- 信号聚合：多策略信号加权合并
- 信号过滤：基于波动率/流动性/时间窗口过滤

#### FR-4.2 仓位管理
- 半 Kelly Criterion 仓位计算
- 单标的最大仓位限制（默认 20%）
- 组合最大持仓数量限制（默认 5）
- 固定比例/风险平价/等风险贡献三种模式

#### FR-4.3 风险控制
- **止损**：固定百分比 / ATR-based / 跟踪止损
- **止盈**：固定百分比 / ATR-based / 跟踪止盈
- **日度风险**：单日最大亏损 -3%，触发暂停
- **周度风险**：单周最大亏损 -5%，触发暂停
- **回撤控制**：组合最大回撤 -10%，触发熔断
- **VaR/CVaR**：Historical + Monte Carlo，日度估算
- **Kill Switch**：一键清仓+停止所有策略

#### FR-4.4 组合管理
- 多策略组合运行
- 策略间相关度监控（相关 > 0.7 预警）
- Risk Parity 权重分配
- 月度再平衡

### 2.5 L5 交易执行层

#### FR-5.1 OKX 实盘接口（CCXT）
- REST API：下单、撤单、查询持仓、查询余额
- WebSocket：实时订单状态推送
- 支持 Order 类型：Limit/Market/Stop-Loss/Take-Profit
- 支持 OCO（One-Cancels-Other）订单
- API Key 安全管理（环境变量/加密存储）

#### FR-5.2 模拟盘（Paper Trade）
- PaperGateway 模拟交易，基于自建 TradingSession 事件驱动引擎
- 与实盘完全相同的交易逻辑（共享 GatewayBase 接口）
- 模拟撮合引擎（基于成交量比例）
- 模拟延迟和滑点

#### FR-5.3 订单管理
- 订单生命周期：Created → Submitted → Accepted → Partial/Full → Cancelled
- 订单超时处理（30s 未成交自动撤单）
- 断线重连和订单状态同步
- 交易记录持久化（DuckDB）

### 2.6 L6 监控与运维层

#### FR-6.1 实时监控
- Grafana Dashboard：资金曲线、持仓、PnL、信号
- Prometheus Metrics：延迟、订单量、策略状态
- 实时告警：钉钉/微信/LINE/Telegram

#### FR-6.2 日志系统
- 结构化日志（JSON 格式）
- 日志级别：DEBUG/INFO/WARN/ERROR
- 日志轮转和归档
- 关键事件审计日志（下单、撤单、风控触发）

#### FR-6.3 Docker 部署
- Docker Compose 一键启动所有服务
- 健康检查和自动重启
- 数据卷持久化
- 本地/云端部署一致

---

## 3. 非功能需求

### 3.1 性能
| 指标 | 目标 |
|------|------|
| 向量化回测（1年日线） | <1s |
| 事件驱动回测（1年日线） | <10s |
| 参数优化（10000 组合） | <60s |
| 实时信号延迟 | <500ms |
| 订单提交延迟 | <1s |
| DuckDB 查询（1亿行） | <100ms |

### 3.2 可靠性
- 断线自动重连（WebSocket + REST API）
- 订单状态丢失自动恢复
- 数据缺失自动检测和补全
- 进程崩溃自动重启（Docker restart policy）

### 3.3 安全性
- API Key 加密存储，不写入代码/日志
- 只读模式：可切换为仅监控不交易
- Kill Switch 硬件/软件触发
- 交易限额：单笔/单日/单策略上限

### 3.4 可维护性
- 模块化六层架构，层间接口清晰
- 配置驱动：策略参数、风控参数、交易参数全部 YAML 配置
- 统一错误处理和异常恢复
- 代码覆盖率 > 70%（核心模块）

### 3.5 可扩展性
- 新交易对：添加配置即可，无需改代码
- 新策略：继承策略基类，实现 on_bar/on_tick
- 新 Gateway：实现 Gateway 接口（未来 A股 miniQMT）
- 新因子：实现 compute 接口，注册到因子表

---

## 4. 分阶段交付

### Phase 1 — MVP（4-6 周）
| 功能 | 优先级 |
|------|--------|
| L1: CCXT 历史数据获取 + Parquet 存储 | P0 |
| L1: DuckDB 查询层 | P0 |
| L2: 基础技术指标（MA/RSI/MACD/ATR/Bollinger） | P0 |
| L3: VectorBT 回测引擎 | P0 |
| L3: 趋势跟踪策略模板 | P0 |
| L4: 基础风控（止损/仓位上限） | P0 |
| L3: Optuna 参数优化 | P1 |
| L4: 信号生成器 | P1 |
| 命令行界面 | P0 |

**Phase 1 不包含**：实盘交易、Web UI、防过拟合体系、监控

### Phase 2 — 验证体系 + 模拟盘（6-8 周）
| 功能 | 优先级 |
|------|--------|
| L3: CPCV + DSR + PBO 防过拟合 | P0 |
| L3: Walk-Forward Optimization | P0 |
| L3: 事件驱动验证引擎 | P0 |
| L5: PaperTrade 模拟盘 | P0 |
| L4: 完整风控体系（Kelly/VaR/熔断） | P0 |
| L6: Grafana + Prometheus 监控 | P1 |
| L6: 告警（Telegram/LINE） | P1 |
| Web UI | P2 |

### Phase 3 — 实盘 + AI 扩展（8-12 周）
| 功能 | 优先级 |
|------|--------|
| L5: OKX 实盘（CCXT） | P0 |
| L5: Kill Switch | P0 |
| L4: 组合管理（Risk Parity） | P0 |
| L2: AI 因子挖掘（Qlib RD-Agent） | P1 |
| L2: 情绪分析（FinBERT） | P1 |
| L1: Delta Lake (可选) | P2 |
| Docker Compose 完整部署 | P0 |

---

## 5. 数据模型

### 5.1 K线数据 (Parquet)
```
symbol: string      # 交易对，如 BTC/USDT
timestamp: int64    # Unix 毫秒时间戳
open: float64
high: float64
low: float64
close: float64
volume: float64
# 分区: symbol/year/month
```

### 5.2 交易记录 (DuckDB)
```sql
CREATE TABLE trades (
    trade_id    TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT CHECK(side IN ('buy','sell')),
    order_type  TEXT CHECK(order_type IN ('market','limit','stop')),
    price       DOUBLE NOT NULL,
    quantity    DOUBLE NOT NULL,
    fee         DOUBLE DEFAULT 0,
    fee_currency TEXT,
    pnl         DOUBLE,
    timestamp   BIGINT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.3 策略信号 (DuckDB)
```sql
CREATE TABLE signals (
    signal_id   TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    direction   INTEGER CHECK(direction IN (-1, 0, 1)),
    strength    DOUBLE CHECK(strength BETWEEN 0 AND 1),
    price       DOUBLE NOT NULL,
    timestamp   BIGINT NOT NULL,
    metadata    TEXT  -- JSON
);
```

### 5.4 风控事件 (DuckDB)
```sql
CREATE TABLE risk_events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,  -- stop_loss, drawdown_breach, kill_switch, etc.
    strategy_id TEXT,
    symbol      TEXT,
    severity    TEXT CHECK(severity IN ('warn','critical','emergency')),
    message     TEXT,
    action_taken TEXT,
    timestamp   BIGINT NOT NULL
);
```

---

## 6. 接口定义

### 6.1 策略接口
```python
class StrategyBase(ABC):
    @abstractmethod
    def on_init(self, ctx: StrategyContext) -> None: ...

    @abstractmethod
    def on_bar(self, bar: Bar) -> None: ...

    @abstractmethod
    def on_tick(self, tick: Tick) -> None: ...

    def on_order(self, order: Order) -> None: ...
    def on_trade(self, trade: Trade) -> None: ...
```

### 6.2 Gateway 接口
```python
class GatewayBase(ABC):
    @abstractmethod
    def connect(self, config: dict) -> None: ...

    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None: ...

    @abstractmethod
    def send_order(self, order: OrderRequest) -> str: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def query_position(self) -> list[Position]: ...

    @abstractmethod
    def disconnect(self) -> None: ...
```

### 6.3 因子接口
```python
class FactorBase(ABC):
    name: str
    dependencies: list[str] = []

    @abstractmethod
    def compute(self, df: pd.DataFrame, **params) -> pd.Series: ...
```

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 策略过拟合 | 高 | 高 | CPCV+DSR+PBO 体系 |
| OKX API 限制 | 中 | 中 | 请求限流 + 重试 + WebSocket |
| 极端行情滑点 | 中 | 高 | ATR 止损 + 流动性过滤 |
| 系统故障 | 低 | 高 | Docker 自动重启 + Kill Switch |
| API Key 泄露 | 低 | 极高 | 加密存储 + IP 白名单 + 只读模式 |
| 自建引擎维护负担 | 中 | 中 | 统一 TradingSession 架构降低复杂度 + 充分单元测试覆盖 |

---

## 8. 验收标准

### Phase 1 MVP
- [ ] 能获取 BTC/USDT 历史 K线并存储为 Parquet
- [ ] 能用 DuckDB 查询历史数据
- [ ] 趋势跟踪策略在 VectorBT 回测中 Sharpe > 1.0
- [ ] Optuna 参数优化能找到最优参数
- [ ] 命令行能运行完整回测流程

### Phase 2 验证体系
- [ ] CPCV 28 条路径全部通过（PBO < 0.5）
- [ ] DSR > 0.95
- [ ] Walk-Forward OOS Efficiency > 50%
- [ ] PaperTrade 模拟运行 ≥30 天
- [ ] 模拟盘与回测偏差 < 10%

### Phase 3 实盘
- [ ] OKX 实盘小额运行 ≥90 天
- [ ] 最大回撤 < 15%
- [ ] Kill Switch 测试通过
- [ ] Docker Compose 一键部署