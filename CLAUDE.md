# QuantFlow — 个人 Crypto 量化交易系统

## 项目概述
面向个人/小团队的 Crypto 量化交易系统（OKX），覆盖策略研究→回测验证→模拟盘→实盘的完整闭环，内置前沿防过拟合体系和模块化六层架构。

## 架构
六层分层架构：L1 数据 → L2 指标因子 → L3 策略研发 → L4 信号风控 → L5 交易执行 → L6 监控运维

**设计原则**：
- 层间单向依赖，低层不依赖高层
- 接口驱动（Protocol/ABC），内部实现可替换
- 配置外置，策略/风控/API 凭证全部 YAML/ENV
- 事件解耦，策略不直接调用 Gateway
- parity 仅 paper↔live（TradingSession 统一 paper/live 执行路径）；backtest 走独立 BacktestEngine（纯向量化），不在 parity 范围（.workflow/specs/architecture-constraints.md S-20260722-pd2y）

## 技术栈
- Python 3.11+, CCXT (OKX), 自建 BacktestEngine（pandas/numpy 向量化）, Optuna, DuckDB+Parquet, Redis
- 自建事件驱动引擎（TradingSession），不依赖外部引擎库
- 防过拟合：CPCV + DSR + PBO + WFO (purgedcv)
- 风控：半Kelly + VaR/CVaR + 回撤熔断 + Kill Switch
- 监控：Grafana + Prometheus, 告警 Telegram/LINE
- 部署：Docker Compose（Compose 路径：docker/docker-compose.yaml）
- AI(V3)：Meta-Labeling + FinBERT 情绪（已实现+测试）；Qlib RD-Agent 因子挖掘（骨架已实现且 CLI 接线；qlib 为可选依赖，深度集成待 P2）

## 开发规范

### 代码质量
- 使用 `ruff` format + lint（配置见 pyproject.toml）
- 使用 `mypy --strict` 类型检查
- 测试覆盖率 fail_under = 100（行+分支双 100% 门禁；见 pyproject.toml [tool.coverage.report]）
- 所有 async 函数使用 `async/await`，不用回调
- 导入顺序：标准库 → 第三方 → 项目内（ruff isort 管理）

### 安全
- API Key 只从环境变量读取，不写入代码/日志
- 实盘模式必须启用 Kill Switch
- .env 文件不提交到 Git（已在 .gitignore 中）

### 配置
- 策略/风控参数全部 YAML 驱动（quantflow/config/）
- 新策略只需：继承 StrategyBase + 添加 YAML 配置
- 配置优先级：命令行参数 > 环境变量 > YAML 默认值

### 数据
- Parquet Hive 分区格式：symbol/year/month
- DuckDB 零导入查询 Parquet
- Feature Store 确保研究+实盘特征一致性
- 时间点安全查询，防止未来数据泄漏

### 测试
- 单元测试：tests/unit/
- 集成测试：tests/integration/
- Live 测试标记 `@pytest.mark.live`（需要 API 连接）
- 慢测试标记 `@pytest.mark.slow`
- 使用 pytest-asyncio 进行 async 测试

## 关键目录
```
quantflow/
├── data/           # L1 数据层 (CCXT获取/清洗/Parquet+DuckDB/FeatureStore/Redis)
├── indicators/     # L2 指标层 (21因子/注册表/趋势/动量/波动/成交量)
├── strategy/       # L3 策略层 (回测/优化/验证/模板/AI因子/情绪)
│   ├── research/   #   回测引擎 + Optuna优化 + 报告生成
│   ├── validation/ #   CPCV + DSR + PBO + WFO + GO/NO-GO门
│   └── templates/  #   趋势跟踪 + 均值回归
├── signal/         # L4 信号风控 (信号生成/风控引擎/仓位/风险指标/组合)
├── execution/      # L5 执行层 (OKX/Paper/执行引擎/订单/持仓/KillSwitch)
├── monitoring/     # L6 监控 (Prometheus指标/告警/日志)
├── reconciliation/ # 对账引擎 (实盘/本地状态一致性)
├── trading/        # TradingSession 别名 re-export
├── web/            # Station 后端 (aiohttp + 业务前端静态托管)
├── common/         # 公共 (数据模型/事件总线/配置/异常)
├── cli/            # CLI入口 (Typer + Rich)
└── config/         # 配置文件 (default.yaml + strategies/)
```

## CLI 命令
```bash
quantflow download --symbol BTC/USDT --start 2024-01-01
quantflow research --strategy trend_following --symbol BTC/USDT
quantflow optimize --strategy trend_following --method bayesian
quantflow validate --strategy trend_following --method gate
quantflow run --mode paper --strategy trend_following
quantflow ai rdagent --symbol BTC/USDT
quantflow status
```

## 分阶段
- Phase 1 MVP ✅：数据+指标+回测+单策略+CLI
- Phase 2 ✅：防过拟合验证(CPCV/DSR/WFO)+模拟盘+完整风控+监控
- Phase 3 ✅：OKX实盘+AI因子+情绪分析+组合管理

> 注：以上 Phase 1/2/3 为历史 MVP 完成轴。roadmap M3 的 deep-research 改进（P0 数据层防泄漏、P1 风控层补齐 [P1-verify PASS 2026-07-21]、P2 AI 层升级 [未启动]）+ 2026-07-25 Wave 1-5 多 book reconcile 一致性收口为进行中的工程化迭代，详见 `.workflow/roadmap.md`。（drift-realign DFT-7a9e6b0c 修正，避免 Phase 3 ✅ 误读为 P2 AI 升级已完成——Qlib RD-Agent 仍未集成，见 `strategy/ai_factors.py`。）

## 核心接口
- `StrategyBase`: `on_init(ctx)`, `on_bar(ctx, bar)`, `on_tick(ctx, tick)`, `generate_signals(df) -> (entries, exits)`
- `GatewayBase`: `connect(config)`, `send_order(order) -> str`, `cancel_order(id, symbol) -> bool`, `query_positions() -> list[Position]`
- `FactorBase`: `compute(df, **params) -> Series`
- `EventBus`: `subscribe(event_type, handler)`, `publish(event)` — 6种核心事件类型

## 数据流
```
CCXT/WebSocket → Redis Cache → EventBus(BAR) → Strategy.on_bar()
                                         ↓
                               SignalGenerator → RiskEngine.check()
                                         ↓
                               PositionSizer.size() → ExecutionEngine.submit()
                                         ↓
                               OKXGateway/PaperGateway → EventBus(ORDER)
                                         ↓
                               Prometheus + Grafana + Telegram Alert
```

## 验证管道
```
策略参数 → pandas/numpy向量化快速筛选 → Optuna精调 → CPCV多路径 → DSR修正 → WFO前向 → GO/NO-GO
```

## 扩展指南
- 新交易对：添加配置即可，无需改代码
- 新策略：继承 StrategyBase，实现 on_bar + generate_signals，添加 YAML 配置
- 新 Gateway：实现 GatewayBase（如未来 A 股 miniQMT）
- 新因子：继承 FactorBase，实现 compute，注册到 FactorRegistry

## 开发命令
```bash
# 格式化 + lint
ruff check --fix . && ruff format .

# 类型检查
mypy quantflow/

# 测试
pytest tests/ -v
pytest tests/ --cov=quantflow --cov-report=html

# 安装
pip install -e ".[dev]"
```