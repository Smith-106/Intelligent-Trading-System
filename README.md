# QuantFlow

> 当前版本 **v0.7.0** — 详见 [docs/release/v0.7.0.md](docs/release/v0.7.0.md)

个人 Crypto 量化交易系统 — 从策略研究到实盘交易的完整闭环。

## 产品定位（先读）

**个人 / 小团队 Crypto 中低频 · paper-first · 验证门驱动的研究 OS（OKX）。**

| 是 | 不是 |
|----|------|
| 防过拟合研究 → GO/NO-GO → paper 日课 | 机构 OEMS / 多所 HFT 平台 |
| 成本保真（fee×slip 网格强制） | SaaS 跟单 / 手机托管 bot |
| 共享账本 multi-symbol + 可选 symbol-level RP | 以 GitHub stars 定义成功 |
| paper↔live 路径语义一致 | 回测与 paper 字节级等价承诺 |

**明确非目标**：Rust 执行内核重写、做市、机构级 OMS、默认开启组合优化（`default.yaml` 中 `portfolio_optimization.enabled=false`）。

**路径 A / B（勿混比）**

| 路径 | 命令 | nested 方向门 | 用途 |
|------|------|---------------|------|
| A 日常 paper | `quantflow run --mode paper …` | 否 | 日课观察 |
| B 研究 GO | `python scripts/run_baseline0.py` | 是 | 与 `gate.json` 对齐 |

无密钥可复现入口：[docs/demo/](docs/demo/) · `python scripts/demo_public_pack.py --check`  
独立公开文档仓（Apache-2.0）：[Smith-106/quantflow-docs-demo](https://github.com/Smith-106/quantflow-docs-demo)

## 特性

- **全链路覆盖**：数据获取 → 指标计算 → 策略回测 → 防过拟合验证 → 模拟盘 → 实盘
- **防过拟合**：CPCV 组合交叉验证 + DSR 稳定性 + PBO 过拟合概率 + WFO 滚动前进 + GO/NO-GO 门
- **风控完备**：半 Kelly 仓位 + VaR/CVaR + 回撤熔断 + Kill Switch（实盘模式强制启用）
- **事件驱动**：自建 TradingSession 引擎，回测/模拟/实盘统一架构
- **指标表面（W18c 口径）**：21 经典核心 + 扩展（supertrend/DEMA/stochRSI/Keltner/Donchian/session VWAP/OBV slope/CVD proxy）+ 6 个 Elliott Wave 注册名（wave 需专用管道），纯 pandas/numpy
- **AI 增强**：Meta-Labeling + FinBERT 情绪分析（已实现）；Qlib RD-Agent 因子挖掘骨架（CLI 已接线，qlib 为可选依赖）
- **QuantFlow Station**：React + Vite 现代前端 + aiohttp 业务后端，23 个 REST 端点 + CSRF/Token 安全防护
- **对账引擎**：持仓漂移检测 + 孤儿订单发现 + 审计日志 + 会话崩溃恢复（Checkpoint 状态存储）
- **数据质量**：实时数据流健康监控 + Redis 降级 fallback
- **交易所健康**：单交易所熔断器（滑窗错误率 + 限频检测 + 滞后恢复）
- **多源数据**：Funding Rate / Open Interest 元数据采集（自限频 + 指数退避）
- **智能告警**：ALERT_ROUTING 矩阵（15 类别 x 4 优先级）+ 滑动窗口去重
- **配置驱动**：策略参数、风控规则、交易对全部 YAML 管理，零硬编码
- **多 Symbol 组合**：共享账本 multi-symbol 回放 + **symbol-level 周期再平衡 Risk Parity**（WFO OOS 验证）
- **研究保真**：paper 路径注入 fee/slippage；`research_risk_bypass` 双报研究/生产风控
- **Dual-path 研究 OS（v0.7）**：Path A 超额 / Path B TPSL 分轴；promotion 指纹诚实接线；PIT 审计；多标的并列报告；会话健康指标

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
│  L2 指标因子  经典+扩展 / 波浪(registry) / 量能代理      │
├─────────────────────────────────────────────────┤
│  L1 数据层    CCXT / DuckDB+Parquet / Redis       │
└─────────────────────────────────────────────────┘

横切层：common（公共模型/事件总线/配置/校验/异常）
       cli（Typer CLI）· web（QuantFlow Station）· trading（TradingSession 别名）
```

> 层间单向依赖（低层不依赖高层）。`TradingSession` 与 `web/`、`cli/` 是合法的编排/集成边界，跨层组合各层。

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

# 模拟盘运行（默认单币）
quantflow run --mode paper --strategy trend_following

# Baseline-0 日常 paper（三币共享账本 + symbol RP；验收口径 paper-first）
python scripts/preflight_baseline0_paper.py
quantflow run --mode paper --strategy trend_following \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT --timeframe 1h --interval 60 \
  --capital 100000 --config quantflow/config/paper_baseline0_overlay.yaml
# 清单: docs/research/baseline0-paper-run-checklist.md

# 实盘运行（实盘模式强制启用 Kill Switch，不可关闭；非 Baseline-0 验收路径）
quantflow run --mode live --strategy trend_following

# 指定交易对、周期与轮询间隔
quantflow run --mode paper --strategy trend_following --symbol BTC/USDT --timeframe 1h --interval 60

# 跨层性能基线（数据/指标/研究/验证/运行时/执行路径，带阈值门）
quantflow benchmark

# AI 因子挖掘（Qlib RD-Agent 骨架；qlib 未安装时打印安装提示）
quantflow ai rdagent --symbol BTC/USDT

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
│   ├── fetcher.py      #   CCXT 数据获取（K线/Ticker/Trade，async）
│   ├── cleaner.py      #   数据清洗 + 防未来泄漏校验
│   ├── store.py        #   DuckDB + Parquet 存储（Hive 分区 symbol/year/month）
│   ├── feature_store.py#   时间点安全特征工程
│   ├── redis_cache.py  #   Redis 实时数据缓存
│   ├── mtf_aligner.py  #   多时间框架对齐
│   ├── dq_monitor.py   #   数据质量实时监控
│   └── market_meta_fetcher.py # 市场元数据（资金费率/持仓量）
├── indicators/         # L2 指标因子层（经典+扩展；wave 走 registry）
│   ├── base.py         #   FactorBase + FactorRegistry 注册表
│   ├── engine.py       #   因子计算引擎（batch_calculate/compute_all）
│   ├── trend.py        #   趋势（SMA/EMA/MACD/Supertrend/ADX/DEMA）
│   ├── momentum.py     #   动量（RSI/StochRSI/Stochastic/Williams%R）
│   ├── volatility.py   #   波动（ATR/BB/Keltner/Donchian）
│   ├── volume.py       #   成交量（OBV/VWAP/session_vwap/OBV slope/CVD proxy）
│   ├── regime.py       #   市场状态检测（策略门控）
│   └── zigzag/wave_*   #   Elliott Wave 子系统（共识 pivot / 铁律 / Fib）
├── strategy/           # L3 策略研发层
│   ├── base.py         #   StrategyBase 双模式接口
│   ├── engine.py       #   TradingSession 事件驱动引擎
│   ├── catalog.py      #   策略注册表（7 策略 + 工厂 + 参数空间）
│   ├── ai_factors.py   #   AI 因子（Meta-Labeling）
│   ├── rd_agent.py     #   Qlib RD-Agent 因子挖掘骨架（可选 qlib）
│   ├── sentiment.py    #   情绪分析（FinBERT + RSS）
│   ├── elliott_wave_strategy.py # 波浪理论策略
│   ├── research/       #   回测 + 优化
│   │   ├── backtest.py #     BacktestEngine（纯 pandas/numpy，已弃用 VectorBT）
│   │   └── optimizer.py#     Optuna 超参优化
│   ├── validation/     #   防过拟合验证
│   │   └── gate.py     #     CPCV/DSR/PBO/WFO + GO/NO-GO
│   └── templates/      #   策略模板（7 个）
│       ├── trend_following.py
│       ├── mean_reversion.py
│       ├── volatility_breakout.py
│       ├── funding_rate.py
│       ├── momentum_rotation.py
│       ├── ml_ensemble.py
│       └── elliott_wave.py
├── signal/             # L4 信号风控层
│   ├── generator.py    #   信号生成与聚合
│   ├── risk_engine.py  #   风控引擎（7 检查短路流水线）
│   ├── risk_metrics.py #   VaR/CVaR/Sharpe/Sortino/Calmar
│   ├── position_sizer.py#  仓位管理（半 Kelly）
│   ├── scaling_position_sizer.py # 分阶段建仓（试仓/加仓/追仓）
│   └── portfolio.py    #   组合管理
├── execution/          # L5 交易执行层
│   ├── gateway_base.py #   GatewayBase 抽象接口
│   ├── okx_gateway.py  #   OKX 实盘网关（CCXT async）
│   ├── paper_gateway.py#   模拟盘网关
│   ├── engine.py       #   执行引擎
│   ├── order_manager.py#   订单管理
│   ├── position_manager.py# 持仓管理
│   ├── exchange_health.py#   交易所健康监控（熔断器/滑窗错误率/限频检测）
│   ├── kill_switch.py  #   紧急熔断
│   └── state_store.py  #   Checkpoint 状态存储（崩溃恢复）
├── monitoring/         # L6 监控运维层
│   ├── metrics.py      #   Prometheus 指标
│   ├── alerts.py       #   告警（Telegram/LINE）
│   └── logger.py       #   结构化日志（structlog）
├── reconciliation/     # 对账层（持仓漂移/孤儿订单/审计日志）
├── common/             # 公共模块
│   ├── models.py       #   数据模型（Bar/Signal/Order/Position + 6 事件类型）
│   ├── event_bus.py    #   事件总线（sync + async）
│   ├── config.py       #   配置加载（CLI > env > YAML）
│   ├── tracing.py      #   分布式追踪支持
│   ├── validators.py   #   安全校验（symbol/column，防注入/遍历）
│   └── exceptions.py   #   自定义异常
├── cli/                # CLI 入口
│   └── main.py         #   Typer + Rich（9 命令）
├── web/                # QuantFlow Station 业务后端
│   ├── app.py          #   aiohttp 应用（23 REST 端点）
│   ├── security.py     #   CSRF + Bearer 认证 + 启动保护
│   ├── service.py      #   应用服务层
│   ├── session_manager.py # 会话生命周期管理
│   └── history.py      #   历史记录持久化
├── trading/            # back-compat 别名（re-export TradingSession）
└── config/             #   配置文件
    ├── default.yaml    #   全局默认配置
    └── strategies/     #   策略专用配置（7 个）
```

> 前端应用位于 `frontend/` 目录，使用 React + Vite + TypeScript 构建。

## 核心接口

### StrategyBase

双模式 API：向量化研究 + 增量实盘，两种模式必须保证信号 parity。

```python
class StrategyBase(ABC):
    def on_init(self, ctx: StrategyContext) -> None: ...
    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None: ...   # 增量 live/paper
    def on_tick(self, ctx: StrategyContext, tick: Tick) -> None: ...
    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]: ...
    # → (entries, exits) boolean Series，向量化研究/回测
```

### GatewayBase

```python
class GatewayBase(ABC):
    async def connect(self, config: dict) -> None: ...             # 连接交易所
    async def send_order(self, order: Order) -> str: ...           # 下单 → 订单 ID
    async def cancel_order(self, order_id: str, symbol: str) -> bool: ...
    async def query_positions(self) -> list[Position]: ...
```

### FactorBase

```python
class FactorBase(ABC):
    def compute(self, df: pd.DataFrame, **params) -> pd.Series: ...  # 计算因子值
```

### EventBus

6 种核心事件类型：`bar` / `tick` / `signal` / `order` / `fill` / `risk`。

```python
bus = EventBus()
bus.subscribe(EVENT_BAR, handler)        # sync 或 async handler
await bus.publish_async(Event(type=EVENT_BAR, data=...))  # 异步发布
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

RiskEngine 7 检查短路流水线（任一失败即拒绝）：仓位限制 → 组合限制 → 策略预算 → 日亏损 → 周亏损 → 回撤 → VaR。

| 层级 | 机制 | 触发条件 |
|------|------|----------|
| 仓位 | 半 Kelly 公式 | 根据 signal.strength 缩放，受 max_position_pct 钳制 |
| 组合 | VaR / CVaR | 单日最大损失 2% / 5% |
| 回撤 | 熔断 | 最大回撤超过阈值 → 暂停交易 |
| 紧急 | Kill Switch | 手动/自动触发 → 撤单 + 全部市价平仓 |

> **安全约束**：实盘模式（`mode=live`）强制启用 Kill Switch，无法通过配置关闭。`ScalingPositionSizer` 输出 `PositionRequest`，由 RiskEngine 做最终权限控制（可拒绝或缩减）。

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


## 多 Symbol 研究（v0.5）

```bash
# 共享账本 equal / shared_cap / shared_risk_parity / silo RP 全窗对比
python scripts/multi_symbol_replay.py

# Walk-forward OOS：equal vs shared symbol RP
python scripts/wfo_shared_rp.py
```

启用引擎内 symbol RP（YAML / `RiskConfig`）：

```yaml
risk:
  portfolio_optimization:
    enabled: true
    method: risk_parity
    level: symbol          # strategy | symbol
    rebalance_every_n_bars: 48
    min_samples: 30
```

发布说明：[docs/release/v0.7.0.md](docs/release/v0.7.0.md) · 运维手册：[docs/operations-guide.md](docs/operations-guide.md) · 告警/会话健康：[docs/ops/alert-taxonomy-session-health.md](docs/ops/alert-taxonomy-session-health.md)

