# Epic 拆解文档 (Epics) — QuantFlow 量化交易系统

## Epic 总览

| Epic | 名称 | Phase | 预估 | 依赖 | 状态 |
|------|------|-------|------|------|------|
| E1 | 数据基础设施 | Phase 1 | 1.5 周 | 无 | ✅ 已完成 |
| E2 | 指标与因子引擎 | Phase 1 | 1 周 | E1 | ✅ 已完成 |
| E3 | 向量化回测引擎 | Phase 1 | 1.5 周 | E1, E2 | ✅ 已完成 |
| E4 | 策略模板与信号生成 | Phase 1 | 1 周 | E2, E3 | ✅ 已完成 |
| E5 | 参数优化引擎 | Phase 1 | 1 周 | E3 | ✅ 已完成 |
| E6 | 基础风控与命令行 | Phase 1 | 1 周 | E4 | ✅ 已完成 |
| E7 | 防过拟合验证体系 | Phase 2 | 2 周 | E3, E5 | ✅ 已完成（框架就绪） |
| E8 | 事件驱动引擎适配 | Phase 2 | 1.5 周 | E4, E6 | ✅ 已完成（框架就绪） |
| E9 | 模拟盘与完整风控 | Phase 2 | 2 周 | E8 | ✅ 已完成（框架就绪） |
| E10 | 监控告警与 Web UI | Phase 2 | 2 周 | E9 | ✅ 已完成（框架就绪） |
| E11 | OKX 实盘对接 | Phase 3 | 2 周 | E9 | ✅ 已完成（框架就绪） |
| E12 | 组合管理与实盘运行 | Phase 3 | 2 周 | E11 | ✅ 已完成（框架就绪） |
| E13 | AI 因子与情绪分析 | Phase 3 | 3 周 | E12 | ✅ 已完成（框架就绪） |

---

## Phase 1 Epics (MVP) ✅

### E1: 数据基础设施
**目标**：建立从 OKX 获取历史/实时数据到 Parquet+DuckDB 存储的完整管道

**Stories**:
- E1-S1: CCXT 数据获取器 — 支持 K线/Ticker/Trade 三种数据类型，增量更新
  - 技术要点：使用 ccxt.async_support，增量更新基于 last_timestamp
  - 涉及文件：`quantflow/data/fetcher.py`
  - 预估工时：8h
  - 优先级：P0

- E1-S2: 数据清洗模块 — 去重、缺失检测、异常值过滤
  - 技术要点：5σ 异常值过滤，时间戳缺失插值，列类型校验
  - 涉及文件：`quantflow/data/cleaner.py`
  - 预估工时：4h
  - 优先级：P0

- E1-S3: Parquet 存储 — Hive 分区 (symbol/year/month)，压缩存储
  - 技术要点：zstd 压缩，增量写入去重，symbol/year/month 三级目录
  - 涉及文件：`quantflow/data/store.py`
  - 预估工时：8h
  - 优先级：P0

- E1-S4: DuckDB 查询层 — 零导入查询 Parquet，时间范围/交易对过滤
  - 技术要点：read_parquet 零导入，WHERE 过滤 pushdown，日期范围查询
  - 涉及文件：`quantflow/data/store.py`
  - 预估工时：4h
  - 优先级：P0

- E1-S5: Feature Store 基础 — 特征计算管道骨架，时间点安全查询
  - 技术要点：时间点安全查询（只使用 timestamp 之前数据），特征版本哈希
  - 涉及文件：`quantflow/data/feature_store.py`
  - 预估工时：8h
  - 优先级：P1

- E1-S6: Redis 实时缓存 — 最新行情缓存，TTL 管理
  - 技术要点：TTL 自动过期，GET/SET 批量操作，连接池
  - 涉及文件：`quantflow/data/redis_cache.py`
  - 预估工时：4h
  - 优先级：P1

**验收标准**:
- [ ] 能下载 BTC/USDT 1年 K线并存储为 Parquet
- [ ] DuckDB 查询 1 年数据 <100ms
- [ ] 增量更新不产生重复数据
- [ ] Feature Store 时间点查询无未来数据泄漏

---

### E2: 指标与因子引擎
**目标**：建立可扩展的指标计算框架

**Stories**:
- E2-S1: FactorBase 接口 + 因子注册表
  - 技术要点：ABC compute 接口，FactorRegistry 自动发现，name + dependencies 声明
  - 涉及文件：`quantflow/indicators/base.py`
  - 预估工时：4h
  - 优先级：P0

- E2-S2: 趋势指标实现（SMA/EMA/DEMA/MACD）
  - 技术要点：pandas-ta 为主，TA-Lib 高性能可选，结果与 TradingView 对齐
  - 涉及文件：`quantflow/indicators/trend.py`
  - 预估工时：6h
  - 优先级：P0

- E2-S3: 动量指标实现（RSI/Stochastic/Williams %R）
  - 技术要点：RSI(14) 标准 Wilder 平滑，StochRSI 双重平滑
  - 涉及文件：`quantflow/indicators/momentum.py`
  - 预估工时：6h
  - 优先级：P0

- E2-S4: 波动指标实现（ATR/Bollinger/Keltner）
  - 技术要点：True Range 计算，BB 标准差倍数可配，Keltner ATR 通道
  - 涉及文件：`quantflow/indicators/volatility.py`
  - 预估工时：4h
  - 优先级：P0

- E2-S5: 成交量指标实现（OBV/Volume SMA/Volume Ratio）
  - 技术要点：OBV 方向判断，Volume Ratio 相对均值计算
  - 涉及文件：`quantflow/indicators/volume.py`
  - 预估工时：4h
  - 优先级：P1

- E2-S6: IndicatorEngine — 批量计算 + 依赖解析
  - 技术要点：拓扑排序解析依赖，批量 compute，缓存中间结果
  - 涉及文件：`quantflow/indicators/engine.py`
  - 预估工时：8h
  - 优先级：P0

**验收标准**:
- [ ] 所有指标结果与 TradingView 对比误差 < 0.1%
- [ ] 因子注册表自动发现所有因子
- [ ] 因子依赖自动解析和计算

---

### E3: 向量化回测引擎
**目标**：基于 VectorBT 的极速回测和策略研究

**Stories**:
- E3-S1: VectorBT 回测封装 — 输入策略参数，输出回测结果
  - 技术要点：vbt.Portfolio.from_signals，init_cash/fees/freq 配置，BacktestResult 数据类
  - 涉及文件：`quantflow/strategy/research/backtest.py`
  - 预估工时：8h
  - 优先级：P0

- E3-S2: 回测报告生成 — Sharpe/Sortino/Calmar/MaxDD/收益曲线
  - 技术要点：BacktestResult.summary()，Markdown/ASCII 双格式，关键指标高亮
  - 涉及文件：`quantflow/strategy/research/report.py`
  - 预估工时：6h
  - 优先级：P0

- E3-S3: 多策略对比 — 并排对比多个参数组合
  - 技术要点：parameter_sweep 批量回测，Sharpe 排序，Top-N 筛选
  - 涉及文件：`quantflow/strategy/research/backtest.py`
  - 预估工时：4h
  - 优先级：P1

- E3-S4: 从 DuckDB/Parquet 加载数据到 VectorBT
  - 技术要点：DataStore.query() → pd.DataFrame，datetime 索引转换，列映射
  - 涉及文件：`quantflow/data/store.py`, `quantflow/cli/main.py`
  - 预估工时：4h
  - 优先级：P0

**验收标准**:
- [ ] 1 年日线回测 <1s
- [ ] 报告包含完整指标和可视化
- [ ] 数据加载零拷贝（Parquet → VBT）

---

### E4: 策略模板与信号生成
**目标**：提供策略基类和第一个完整策略

**Stories**:
- E4-S1: StrategyBase 接口 + StrategyContext
  - 技术要点：ABC on_init/on_bar/on_tick，StrategyContext.emit_signal()，flush_signals()
  - 涉及文件：`quantflow/strategy/base.py`
  - 预估工时：4h
  - 优先级：P0

- E4-S2: 趋势跟踪策略 — MA 排列 + MACD 确认 + RSI 过滤
  - 技术要点：5 过滤器级联（MA/MACD/RSI/ATR/Volume），generate_signals() 向量化
  - 涉及文件：`quantflow/strategy/templates/trend_following.py`
  - 预估工时：8h
  - 优先级：P0

- E4-S3: SignalGenerator — 策略信号标准化输出
  - 技术要点：Signal 数据类（symbol/direction/strength/timestamp/strategy_id），信号聚合
  - 涉及文件：`quantflow/signal/generator.py`
  - 预估工时：4h
  - 优先级：P0

- E4-S4: 策略配置 YAML 驱动
  - 技术要点：strategies/trend_following.yaml，params + exit 分区，CLI 加载
  - 涉及文件：`quantflow/config/strategies/trend_following.yaml`
  - 预估工时：3h
  - 优先级：P0

**验收标准**:
- [ ] 趋势跟踪策略在 BTC/USDT 回测 Sharpe > 1.0
- [ ] 信号格式标准化：{symbol, direction, strength, timestamp, strategy_id}
- [ ] 策略参数全部从 YAML 配置读取

---

### E5: 参数优化引擎
**目标**：Optuna 贝叶斯优化 + 网格搜索

**Stories**:
- E5-S1: Optuna 优化封装 — 目标函数、搜索空间定义
  - 技术要点：optuna_objective(trial)，suggest_int/suggest_float，异常处理返回 -10
  - 涉及文件：`quantflow/strategy/research/optimizer.py`
  - 预估工时：8h
  - 优先级：P0

- E5-S2: GPSampler 贝叶斯优化
  - 技术要点：GPSampler 默认，连续空间高效探索
  - 涉及文件：`quantflow/strategy/research/optimizer.py`
  - 预估工时：4h
  - 优先级：P0

- E5-S3: CmaEsSampler 进化策略
  - 技术要点：CmaEsSampler 连续参数场景，适合多峰优化
  - 涉及文件：`quantflow/strategy/research/optimizer.py`
  - 预估工时：4h
  - 优先级：P1

- E5-S4: 多目标优化（Sharpe + MaxDD）
  - 技术要点：objective 参数选择 sharpe/sortino/calmar/return
  - 涉及文件：`quantflow/strategy/research/optimizer.py`
  - 预估工时：6h
  - 优先级：P1

- E5-S5: 优化结果可视化和导出
  - 技术要点：Rich Table 输出，best_params + best_value，JSON 导出
  - 涉及文件：`quantflow/cli/main.py`
  - 预估工时：4h
  - 优先级：P2

**验收标准**:
- [ ] 200 次 Bayesian trial 找到优于默认参数的结果
- [ ] 多目标 Pareto 前沿可视化
- [ ] 优化结果导出为 JSON

---

### E6: 基础风控与命令行
**目标**：基础止损/仓位限制 + CLI 完整入口

**Stories**:
- E6-S1: RiskEngine 基础 — 仓位上限 + 日度亏损限制
  - 技术要点：4 层检查管道（position_limit/portfolio_limit/daily_loss/drawdown）
  - 涉及文件：`quantflow/signal/risk_engine.py`
  - 预估工时：6h
  - 优先级：P0

- E6-S2: PositionSizer — 固定比例仓位
  - 技术要点：Kelly 方法（kelly_fraction=0.5 半 Kelly），signal.strength 加权
  - 涉及文件：`quantflow/signal/position_sizer.py`
  - 预估工时：4h
  - 优先级：P0

- E6-S3: CLI 入口（Typer）— research / optimize / validate / run / status 命令
  - 技术要点：Typer app，Rich Console/Table 输出，asyncio.run 包装
  - 涉及文件：`quantflow/cli/main.py`
  - 预估工时：8h
  - 优先级：P0

- E6-S4: CLI 报告输出 — 表格 + ASCII 图表
  - 技术要点：Rich Table 格式化，_display_cpcv/_display_dsr/_display_wfo 辅助函数
  - 涉及文件：`quantflow/cli/main.py`
  - 预估工时：4h
  - 优先级：P1

**验收标准**:
- [ ] CLI 能运行完整回测流程：下载数据→计算指标→回测→输出报告
- [ ] 风控能在回测中正确触发止损
- [ ] 单标的仓位不超过 20%

---

## Phase 2 Epics (验证体系 + 模拟盘) ✅

### E7: 防过拟合验证体系
**目标**：CPCV + DSR + PBO + WFO 完整验证管道

**Stories**:
- E7-S1: CPCV 实现 — purgedcv 集成，8组×2测试=28路径
  - 技术要点：combinatorial 分组，embargo 期消除泄漏，PBO < 0.5 通过
  - 涉及文件：`quantflow/strategy/validation/cpcv.py`
  - 预估工时：12h
  - 优先级：P0

- E7-S2: DSR 实现 — 多次测试偏差修正
  - 技术要点：期望最大 Sharpe 计算，DSR > 0.95 通过阈值
  - 涉及文件：`quantflow/strategy/validation/dsr.py`
  - 预估工时：8h
  - 优先级：P0

- E7-S3: PBO 实现 — 过拟合概率量化
  - 技术要点：IS/OOS 分组训练，过拟合概率 < 0.5 阈值
  - 涉及文件：`quantflow/strategy/validation/pbo.py`
  - 预估工时：8h
  - 优先级：P0

- E7-S4: WFO 实现 — Anchored + Rolling 模式
  - 技术要点：滚动窗口 vs 固定起点，OOS Efficiency > 50%
  - 涉及文件：`quantflow/strategy/validation/wfo.py`
  - 预估工时：8h
  - 优先级：P0

- E7-S5: GO/NO-GO 决策门 — 自动化验证管道
  - 技术要点：CPCV→DSR→WFO 顺序，任一失败即 NO-GO，validation_gate()
  - 涉及文件：`quantflow/strategy/validation/gate.py`
  - 预估工时：6h
  - 优先级：P0

- E7-S6: Triple-Barrier Method 标注
  - 技术要点：价格触碰三重屏障（止盈/止损/时间），事件标注
  - 涉及文件：`quantflow/strategy/validation/barriers.py`
  - 预估工时：6h
  - 优先级：P1

- E7-S7: Minimum Track Record Length 计算
  - 技术要点：基于 Sharpe 和回撤计算最少验证天数
  - 涉及文件：`quantflow/strategy/validation/dsr.py`
  - 预估工时：4h
  - 优先级：P2

**验收标准**:
- [ ] CPCV 28 路径全部运行，输出 PBO 值
- [ ] DSR 自动计算，阈值 0.95
- [ ] WFO OOS Efficiency 自动计算
- [ ] 完整管道：参数→CPCV→DSR→WFO→GO/NO-GO

---

### E8: 事件驱动引擎
**目标**：自建事件驱动引擎（TradingSession）用于验证/实盘

**Stories**:
- E8-S1: EventBus 实现 — 发布-订阅，线程安全
  - 技术要点：defaultdict(list) handler 管理，6 种事件类型常量，异常隔离
  - 涉及文件：`quantflow/common/event_bus.py`
  - 预估工时：4h
  - 优先级：P0

- E8-S2: TradingSession 事件驱动引擎 — 策略在自建引擎中运行
  - 技术要点：on_bar→strategy→signal→risk→sizer→execution 管道编排，mode 路由
  - 涉及文件：`quantflow/strategy/engine.py`
  - 预估工时：12h
  - 优先级：P0

- E8-S3: 真实滑点模拟 — 按成交量比例
  - 技术要点：PaperGateway 滑点模型，基于成交量估算冲击成本
  - 涉及文件：`quantflow/execution/paper_gateway.py`
  - 预估工时：6h
  - 优先级：P0

- E8-S4: 手续费精确计算 — Maker/Taker 分开
  - 技术要点：fee_rate 参数化，Maker/Taker 不同费率
  - 涉及文件：`quantflow/execution/paper_gateway.py`
  - 预估工时：4h
  - 优先级：P1

- E8-S5: 回测-实盘一致性验证 — 同一策略两种模式结果对比
  - 技术要点：TradingSession 统一 backtest/paper/live，StrategyBase 代码复用
  - 涉及文件：`quantflow/strategy/engine.py`
  - 预估工时：8h
  - 优先级：P0

**验收标准**:
- [ ] VectorBT 和事件驱动引擎回测同一策略，净值曲线偏差 <5%（扣除滑点手续费差异）
- [ ] 事件驱动引擎模拟包含真实滑点和手续费

---

### E9: 模拟盘与完整风控
**目标**：PaperTrade + 完整风控体系

**Stories**:
- E9-S1: PaperGateway 实现 — 本地模拟撮合
  - 技术要点：市价即时成交，fee_rate 模拟，现金/持仓更新
  - 涉及文件：`quantflow/execution/paper_gateway.py`
  - 预估工时：8h
  - 优先级：P0

- E9-S2: OKXGateway 骨架 — CCXT async 封装（先仅用于 PaperTrade 的行情获取）
  - 技术要点：ccxt.async_support.okx，sandbox 模式，load_markets 初始化
  - 涉及文件：`quantflow/execution/okx_gateway.py`
  - 预估工时：8h
  - 优先级：P0

- E9-S3: Kelly Criterion 仓位计算（半Kelly）
  - 技术要点：f* = (p*b - q) / b，kelly_fraction=0.5 半仓，signal.strength 缩放
  - 涉及文件：`quantflow/signal/position_sizer.py`
  - 预估工时：6h
  - 优先级：P0

- E9-S4: VaR/CVaR 风险估算
  - 技术要点：Historical VaR + Monte Carlo，置信度 95%/99%
  - 涉及文件：`quantflow/signal/risk_metrics.py`
  - 预估工时：8h
  - 优先级：P0

- E9-S5: 回撤熔断机制 — 组合回撤 >10% 暂停
  - 技术要点：Portfolio.current_drawdown 计算，max_drawdown 阈值检查
  - 涉及文件：`quantflow/signal/risk_engine.py`, `quantflow/signal/portfolio.py`
  - 预估工时：6h
  - 优先级：P0

- E9-S6: Kill Switch 实现
  - 技术要点：stop_all() + cancel_all() + 市价平仓 + 紧急告警
  - 涉及文件：`quantflow/execution/kill_switch.py`
  - 预估工时：6h
  - 优先级：P0

- E9-S7: 模拟盘持久化运行 — 交易记录写入 DuckDB
  - 技术要点：trades/signals/risk_events 表写入，定期 flush
  - 涉及文件：`quantflow/data/store.py`, `quantflow/execution/order_manager.py`
  - 预估工时：6h
  - 优先级：P1

**验收标准**:
- [ ] PaperTrade 运行 7 天无异常
- [ ] Kelly 仓位计算正确（与手动验证一致）
- [ ] Kill Switch 测试：触发后所有持仓清空
- [ ] 模拟盘交易记录完整持久化

---

### E10: 监控告警与 Web UI
**目标**：Grafana 监控 + 告警 + QuantFlow Station Web UI

**Stories**:
- E10-S1: Prometheus 指标导出
  - 技术要点：Counter/Gauge/Histogram 指标，start_http_server，update_portfolio_metrics()
  - 涉及文件：`quantflow/monitoring/metrics.py`
  - 预估工时：6h
  - 优先级：P0

- E10-S2: Grafana Dashboard 模板 — 资金曲线/持仓/PnL/信号
  - 技术要点：PromQL 查询，4 面板（Portfolio/Positions/Signals/Risk）
  - 涉及文件：`docker/prometheus.yml`, Grafana JSON 模板
  - 预估工时：8h
  - 优先级：P1

- E10-S3: Telegram/LINE 告警通知
  - 技术要点：AlertManager 类，severity 分级，async 发送
  - 涉及文件：`quantflow/monitoring/alerts.py`
  - 预估工时：6h
  - 优先级：P1

- E10-S4: Docker Compose 部署配置
  - 技术要点：redis/prometheus/grafana 服务，健康检查，volume 持久化
  - 涉及文件：`docker/docker-compose.yaml`, `docker/Dockerfile`
  - 预估工时：4h
  - 优先级：P0

- E10-S5: QuantFlow Station Web UI 集成（策略管理/回测可视化）
  - 技术要点：FastAPI/Streamlit 可选，策略 CRUD，回测结果展示
  - 涉及文件：新建 `quantflow/web/` 模块
  - 预估工时：16h
  - 优先级：P2

**验收标准**:
- [ ] Grafana 实时显示策略运行状态
- [ ] 风控事件触发 Telegram 告警
- [ ] Docker Compose 一键启动所有服务
- [ ] Web UI 能查看回测结果和策略配置

---

## Phase 3 Epics (实盘 + AI) ✅

### E11: OKX 实盘对接
**目标**：OKX 实盘交易完整闭环

**Stories**:
- E11-S1: OKXGateway REST API — 下单/撤单/查询
  - 技术要点：ccxt.okx async，create_order/cancel_order/fetch_positions
  - 涉及文件：`quantflow/execution/okx_gateway.py`
  - 预估工时：8h
  - 优先级：P0

- E11-S2: OKXGateway WebSocket — 实时行情+订单状态
  - 技术要点：ccxt.watch_order_book/watch_orders，自动重连
  - 涉及文件：`quantflow/execution/okx_gateway.py`
  - 预估工时：8h
  - 优先级：P0

- E11-S3: OrderManager — 订单生命周期管理
  - 技术要点：Created→Submitted→Accepted→Filled/Cancelled 状态机，超时检查
  - 涉及文件：`quantflow/execution/order_manager.py`
  - 预估工时：8h
  - 优先级：P0

- E11-S4: PositionManager — 持仓实时跟踪
  - 技术要点：update_market_price()，unrealized_pnl 计算，多 symbol 管理
  - 涉及文件：`quantflow/execution/position_manager.py`
  - 预估工时：6h
  - 优先级：P0

- E11-S5: 断线重连 + 状态恢复
  - 技术要点：reconnect_interval 配置，订单状态同步，PositionManager 恢复
  - 涉及文件：`quantflow/execution/engine.py`, `quantflow/execution/okx_gateway.py`
  - 预估工时：8h
  - 优先级：P0

- E11-S6: API Key 安全管理
  - 技术要点：环境变量读取，不写入日志/代码，sandbox 模式切换
  - 涉及文件：`.env.example`, `quantflow/execution/okx_gateway.py`
  - 预估工时：4h
  - 优先级：P0

- E11-S7: OKX sandbox 模式测试
  - 技术要点：set_sandbox_mode(True)，模拟盘 API，完整下单/撤单/查询流程
  - 涉及文件：`quantflow/execution/okx_gateway.py`
  - 预估工时：6h
  - 优先级：P0

**验收标准**:
- [ ] OKX sandbox 模式完整下单/撤单/查询流程
- [ ] WebSocket 断线自动重连 <5s
- [ ] API Key 不出现在日志/代码中
- [ ] 订单状态与 OKX 后台一致

---

### E12: 组合管理与实盘运行
**目标**：多策略组合 + 长期实盘运行

**Stories**:
- E12-S1: PortfolioManager — 多策略组合运行
  - 技术要点：set_allocation() 等权分配，update_position() 价格更新
  - 涉及文件：`quantflow/signal/portfolio.py`
  - 预估工时：8h
  - 优先级：P0

- E12-S2: Risk Parity 权重分配
  - 技术要点：inverse-volatility 加权，月度再平衡
  - 涉及文件：`quantflow/signal/portfolio.py`
  - 预估工时：8h
  - 优先级：P0

- E12-S3: 策略相关度监控
  - 技术要点：收益率相关矩阵，>0.7 预警，DuckDB 查询
  - 涉及文件：`quantflow/signal/portfolio.py`
  - 预估工时：6h
  - 优先级：P1

- E12-S4: 月度再平衡
  - 技术要点：calendar 触发，权重偏离阈值，自动调仓
  - 涉及文件：`quantflow/signal/portfolio.py`
  - 预估工时：6h
  - 优先级：P1

- E12-S5: 均值回归策略模板
  - 技术要点：RSI<30 + BB 下轨 + Volume 确认，generate_signals() 向量化
  - 涉及文件：`quantflow/strategy/templates/mean_reversion.py`
  - 预估工时：8h
  - 优先级：P1

- E12-S6: 实盘小额运行 90 天
  - 技术要点：日志持久化，健康检查，异常恢复
  - 涉及文件：`quantflow/strategy/engine.py`, `quantflow/monitoring/`
  - 预估工时：16h
  - 优先级：P0

- E12-S7: Docker Compose 云端部署（AWS/GCP 轻量实例）
  - 技术要点：Docker 多阶段构建，env_file 注入，restart policy
  - 涉及文件：`docker/docker-compose.yaml`, `docker/Dockerfile`
  - 预估工时：6h
  - 优先级：P1

**验收标准**:
- [ ] 2 个策略同时运行无冲突
- [ ] Risk Parity 权重自动分配
- [ ] 实盘运行 90 天，最大回撤 <15%
- [ ] 云端 Docker 部署稳定运行

---

### E13: AI 因子与情绪分析
**目标**：ML/AI 增强策略

**Stories**:
- E13-S1: Qlib 集成 + RD-Agent 因子挖掘
  - 技术要点：AIFactorEngine.compute_technical_factors()，cross-sectional rank
  - 涉及文件：`quantflow/strategy/ai_factors.py`
  - 预估工时：12h
  - 优先级：P1

- E13-S2: FinBERT 情绪分析模块
  - 技术要点：ProsusAI/finbert 模型，sentiment_score [-1,1]，batch 推理
  - 涉及文件：`quantflow/strategy/sentiment.py`
  - 预估工时：8h
  - 优先级：P1

- E13-S3: 新闻数据采集（Crypto 新闻源）
  - 技术要点：CryptoPanic RSS (免费)，feedparser 解析，日期聚合
  - 涉及文件：`quantflow/strategy/sentiment.py` (NewsCollector)
  - 预估工时：6h
  - 优先级：P1

- E13-S4: Meta-Labeling — 规则策略方向 + ML 仓位大小
  - 技术要点：RandomForestClassifier，primary_signal * model_confidence，OOS 测试
  - 涉及文件：`quantflow/strategy/ai_factors.py`
  - 预估工时：10h
  - 优先级：P0

- E13-S5: MLflow 模型版本管理
  - 技术要点：model 版本追踪，参数/指标记录，A/B 实验
  - 涉及文件：新建 `quantflow/mlflow_compat.py`
  - 预估工时：8h
  - 优先级：P2

- E13-S6: AI 因子纳入 Feature Store
  - 技术要点：FeatureStore 新增 AI 列，sentiment_factor 写入 Parquet
  - 涉及文件：`quantflow/data/feature_store.py`, `quantflow/strategy/ai_factors.py`
  - 预估工时：6h
  - 优先级：P1

- E13-S7: 云 GPU 推理适配（AWS/GCP）
  - 技术要点：torch.cuda 设备检测，模型加载到 GPU，批量推理优化
  - 涉及文件：`quantflow/strategy/sentiment.py`, `quantflow/strategy/ai_factors.py`
  - 预估工时：8h
  - 优先级：P2

**验收标准**:
- [ ] RD-Agent 自动生成 5+ 有效因子（IC > 0.03）
- [ ] FinBERT 情绪得分与市场走势相关性 > 0.3
- [ ] Meta-Labeling 提升策略 Sharpe > 20%
- [ ] 云 GPU 推理端到端 <2s

---

## Epic 依赖关系

```
E1(数据) ──→ E2(指标) ──→ E3(回测) ──→ E5(优化)
     │              │          │
     │              └──────────┼──→ E4(策略) ──→ E6(风控+CLI)
     │                         │
     └─────────────────────────┘
                               │
                    ┌──────────┘
                    ↓
E7(防过拟合) ←── E3 + E5
E8(事件驱动引擎)  ←── E4 + E6
                    │
                    ↓
              E9(模拟盘+风控) ──→ E10(监控)
                    │
                    ↓
              E11(OKX实盘) ──→ E12(组合+实盘运行) ──→ E13(AI因子)
```

---

## MVP 完成定义 (Phase 1 Done When)

- [ ] `python -m quantflow.cli research --strategy trend_following --symbol BTC/USDT` 完整运行
- [ ] 趋势跟踪策略 BTC/USDT 回测 Sharpe > 1.0
- [ ] Optuna 优化 200 trial 找到优于默认参数的结果
- [ ] 所有指标与 TradingView 验证一致
- [ ] DuckDB 查询 1 年数据 <100ms
- [ ] CLI 输出完整回测报告（Sharpe/Sortino/Calmar/MaxDD/收益曲线）