# QuantFlow

个人 Crypto 量化交易系统 — 从策略研究到实盘交易的完整闭环。

## 特性

- **全链路覆盖**：数据获取 → 指标计算 → 策略回测 → 防过拟合验证 → 模拟盘 → 实盘
- **防过拟合**：CPCV 组合交叉验证 + DSR 稳定性 + PBO 过拟合概率 + WFO 滚动前进 + GO/NO-GO 门
- **风控完备**：半 Kelly 仓位 + VaR/CVaR + 回撤熔断 + Kill Switch
- **事件驱动**：自建 TradingSession 引擎，回测/模拟/实盘统一架构
- **AI 增强**（V3）：Meta-Labeling + FinBERT 情绪分析（已实现）；Qlib RD-Agent 因子挖掘（规划中，qlib 为可选依赖）
- **配置驱动**：策略参数、风控规则、交易对全部 YAML 管理，零硬编码

## 架构

```
┌─────────────────────────────────────────────────┐
│  L6 监控运维  Grafana / Prometheus / Telegram    │
├─────────────────────────────────────────────────┤
│  L5 交易执行  OKXGateway / PaperGateway / KillSwitch │
├─────────────────────────────────────────────────┤
│  L4 信号风控  信号生成 / 风控引擎 / 仓位管理       │
├─────────────────────────────────────────────────┤
│  L3 策略研发  回测 / 优化 / 验证 / AI因子         │
├─────────────────────────────────────────────────┤
│  L2 指标因子  21因子 / 趋势 / 动量 / 波动 / 成交量  │
├─────────────────────────────────────────────────┤
│  L1 数据层    CCXT / DuckDB+Parquet / Redis       │
└─────────────────────────────────────────────────┘
```

## 快速开始

### 环境要求

- Python 3.11+
- Redis 7+（缓存 + 实时数据）
- DuckDB（本地分析存储）

### 安装

```bash
# 克隆仓库
git clone <repo-url> && cd 智能交易系统

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"
```

### 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入：
# - OKX_API_KEY / OKX_SECRET / OKX_PASSPHRASE（实盘必需）
# - REDIS_URL（默认 redis://localhost:6379）
# - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID（告警通知）
```

### Docker 部署

```bash
cd docker
docker compose up -d    # 默认将 QuantFlow 暴露到 localhost:18000

# 如需自定义宿主端口
QUANTFLOW_HOST_PORT=8008 docker compose up -d
```

## 使用

```bash
# 下载数据
quantflow download --symbol BTC/USDT --start 2024-01-01

# 策略回测
quantflow research --strategy trend_following --symbol BTC/USDT

# 参数优化
quantflow optimize --strategy trend_following --method bayesian

# 防过拟合验证
quantflow validate --strategy trend_following --method gate

# 模拟盘运行
quantflow run --mode paper --strategy trend_following

# 实盘运行
quantflow run --mode live --strategy trend_following

# 指定交易对、周期与轮询间隔
quantflow run --mode paper --strategy trend_following --symbol BTC/USDT --timeframe 1h --interval 60

# 查看状态
quantflow status

# 启动业务前端
quantflow station --host 127.0.0.1 --port 8088

# 环境自检
python scripts/check_env.py
```

## 项目结构

```
quantflow/
├── data/               # L1 数据层
│   ├── fetcher.py      #   CCXT 数据获取（K线/Ticker/Trade）
│   ├── cleaner.py      #   数据清洗（缺失值/异常值/时间对齐）
│   ├── store.py        #   DuckDB + Parquet 存储
│   ├── feature_store.py#   特征工程与缓存
│   └── redis_cache.py  #   Redis 实时数据缓存
├── indicators/         # L2 指标因子层
│   ├── base.py         #   FactorBase 注册表
│   ├── engine.py       #   因子计算引擎
│   ├── trend.py        #   趋势因子（EMA/SMA/Supertrend）
│   ├── momentum.py     #   动量因子（RSI/MACD/StochRSI）
│   ├── volatility.py   #   波动因子（ATR/BB/Keltner）
│   └── volume.py       #   成交量因子（OBV/VWAP/MFI）
├── strategy/           # L3 策略研发层
│   ├── base.py         #   StrategyBase 接口
│   ├── engine.py       #   TradingSession 事件驱动引擎
│   ├── ai_factors.py   #   AI 因子（Qlib/FinBERT）
│   ├── sentiment.py    #   情绪分析
│   ├── research/       #   回测 + 优化
│   │   ├── backtest.py #     VectorBT 回测引擎
│   │   └── optimizer.py#     Optuna 超参优化
│   ├── validation/     #   防过拟合验证
│   │   └── gate.py     #     CPCV/DSR/PBO/WFO + GO/NO-GO
│   └── templates/      #   策略模板
│       ├── trend_following.py
│       └── mean_reversion.py
├── signal/             # L4 信号风控层
│   ├── generator.py    #   信号生成与聚合
│   ├── risk_engine.py  #   风控引擎（半Kelly/VaR/回撤熔断）
│   ├── risk_metrics.py #   风险指标计算
│   ├── position_sizer.py#  仓位管理
│   └── portfolio.py    #   组合管理
├── execution/          # L5 交易执行层
│   ├── gateway_base.py #   GatewayBase 抽象接口
│   ├── okx_gateway.py  #   OKX 实盘网关
│   ├── paper_gateway.py#   模拟盘网关
│   ├── engine.py       #   执行引擎
│   ├── order_manager.py#   订单管理
│   ├── position_manager.py# 持仓管理
│   └── kill_switch.py  #   紧急熔断
├── monitoring/         # L6 监控运维层
│   ├── metrics.py      #   Prometheus 指标
│   ├── alerts.py       #   告警（Telegram/LINE）
│   └── logger.py       #   结构化日志
├── common/             # 公共模块
│   ├── models.py       #   数据模型（Bar/Signal/Order/Trade）
│   ├── event_bus.py    #   事件总线
│   ├── config.py       #   配置加载
│   └── exceptions.py   #   自定义异常
├── cli/                # CLI 入口
│   └── main.py         #   Click 命令行
└── config/             #   配置文件
    ├── default.yaml    #   全局默认配置
    └── strategies/     #   策略专用配置
```

## 核心接口

### StrategyBase

```python
class StrategyBase(ABC):
    def on_init(self, ctx: Context) -> None: ...    # 初始化
    def on_bar(self, bar: Bar) -> None: ...         # K线回调
    def on_tick(self, tick: Tick) -> None: ...      # Tick 回调
    def generate_signals(self) -> list[Signal]: ...  # 生成信号
```

### GatewayBase

```python
class GatewayBase(ABC):
    def connect(self) -> None: ...                          # 连接交易所
    def send_order(self, order: Order) -> OrderResult: ...  # 下单
    def cancel_order(self, order_id: str) -> bool: ...      # 撤单
    def query_positions(self) -> list[Position]: ...        # 查询持仓
```

### FactorBase

```python
class FactorBase(ABC):
    def compute(self, df: pd.DataFrame, **params) -> pd.Series: ...  # 计算因子值
```

### EventBus

```python
bus = EventBus()
bus.subscribe(EventType.BAR, handler)
bus.publish(Event(EventType.BAR, data=bar))
```

## 防过拟合验证管道

```
策略优化结果
    │
    ▼
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌──────────┐
│  CPCV   │───▶│  DSR    │───▶│  PBO    │───▶│  WFO     │
│ 组合交叉 │    │ 稳定性  │    │ 过拟合  │    │ 滚动前进 │
│ 验证    │    │ 检测    │    │ 概率    │    │ 验证     │
└─────────┘    └─────────┘    └─────────┘    └──────────┘
                                                  │
                                                  ▼
                                           ┌──────────┐
                                           │ GO/NO-GO │
                                           │  门控    │
                                           └──────────┘
```

- **CPCV**：N 组合 K 折交叉验证，避免单次划分偏差
- **DSR**：策略在多时段的稳定性排名
- **PBO**：过拟合概率 < 0.5 才通过
- **WFO**：滚动窗口前向验证，模拟真实交易序列
- **GO/NO-GO**：综合评分，只有通过才允许进入模拟盘

## 风控体系

| 层级 | 机制 | 触发条件 |
|------|------|----------|
| 仓位 | 半 Kelly 公式 | 根据胜率/赔率动态计算 |
| 组合 | VaR / CVaR | 单日最大损失 2% / 5% |
| 回撤 | 熔断 | 最大回撤超过阈值 → 暂停交易 |
| 紧急 | Kill Switch | 手动/自动触发 → 全部平仓 |

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 验证可打包
python -m build

# 代码格式化 + Lint
ruff check --fix .
ruff format .

# 类型检查
mypy quantflow/

# 运行测试
pytest tests/ -v

# 测试覆盖率
pytest tests/ --cov=quantflow --cov-report=html
```

## 配置说明

策略和风控参数通过 YAML 文件管理，位于 `quantflow/config/`：

- `default.yaml`：全局默认配置（数据源、Redis、监控等）
- `strategies/trend_following.yaml`：趋势跟踪策略参数
- 新策略只需在 `strategies/` 下添加对应 YAML 文件

关键配置项参见 `.env.example`。

## 许可

私有项目，仅供个人/小团队使用。
