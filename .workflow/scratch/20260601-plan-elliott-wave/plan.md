# 执行计划 — 柳玉东波浪理论交易系统

> 来源: brainstorm-elliott-wave-20260601
> 覆盖: F-001 ~ F-008, 共 12 个任务, 3 个波次

---

## Wave 1: L2 指标层核心 (4 tasks)

### TASK-001: ZigZag 转折点检测器
- **Feature**: F-001
- **Files**: `quantflow/indicators/zigzag.py`
- **Description**: 实现多参数 ZigZag 指标，自动标记价格转折点，输出 PivotSequence 数据结构
- **Spec**:
  - `ZigZagIndicator(FactorBase)` — compute(df, threshold=5.0) → PivotSequence
  - 支持多参数运行（thresholds=[3.0, 5.0, 7.0]），取 >80% 重叠的共识转折点
  - `PivotSequence` dataclass: `pivots: list[PivotPoint]`, `overlap_ratio: float`
  - `PivotPoint` dataclass: `index: int, price: float, direction: PivotDirection(HIGH|LOW), confidence: float`
  - 使用 UTC 时间，滚动窗口计算（解决 24/7 交易问题 Q4）
- **Acceptance**: 单元测试验证已知 BTC 历史转折点识别准确率 >80%
- **Cross-ref**: C-002 (min_overlap>80%), G-001 (输出PivotSequence供WaveIdentifier消费)

### TASK-002: 浪型识别引擎
- **Feature**: F-001
- **Files**: `quantflow/indicators/wave_identifier.py`, `quantflow/indicators/wave_models.py`
- **Description**: 基于 PivotSequence 推断当前浪型，实现三大铁律验证器，支持回顾/渐进双模式
- **Spec**:
  - `WaveIdentifier` — identify(pivots: PivotSequence) → WaveCount
  - `WaveCount` dataclass: `pattern: WavePattern(IMPULSE|CORRECTIVE|UNKNOWN)`, `current_wave: int`, `waves: dict[int,WaveSegment]`, `mode: AnalysisMode(RETROSPECTIVE|PROGRESSIVE)`, `confidence: float`
  - `WaveSegment` dataclass: `label: int, start: PivotPoint, end: PivotPoint, length_pct: float, retracement_pct: float|None`
  - `IronLawValidator` — validate(wave_count: WaveCount) -> IronLawResult
    - Iron Law 1: W2 不能跌破 W1 起点（两种模式都强制）
    - Iron Law 2: W3 不能是最短（回顾模式强制，渐进模式仅检查+警告，不拒绝分类）→ C-001
    - Iron Law 3: W4 不能进入 W1 价格区间（两种模式都强制，楔形例外标记）
  - `IronLawResult` dataclass: `law1_ok: bool, law2_ok: bool|None, law3_ok: bool, warnings: list[str], violations: list[str]`
- **Acceptance**: 单元测试覆盖三大铁律各种违反场景，渐进模式 W3 违反不拒绝分类
- **Cross-ref**: C-001 (双模式), S-001 (WaveCount→IronLawValidator)

### TASK-003: 斐波那契计算器
- **Feature**: F-002
- **Files**: `quantflow/indicators/fibonacci.py`
- **Description**: 计算斐波那契回撤位和扩展位，标注精确目标价位
- **Spec**:
  - `FibonacciCalculator(FactorBase)` — compute(df, wave_count: WaveCount) → FibonacciLevels
  - 回撤位: 0.236, 0.382, 0.5, 0.618, 0.786
  - 扩展位: 1.0, 1.236, 1.382, 1.618, 2.0, 2.618
  - `FibonacciLevels` dataclass: `retracement: dict[float,float]`, `extension: dict[float,float]`, `key_levels: list[FibonacciLevel]`
  - `FibonacciLevel` dataclass: `ratio: float, price: float, level_type: Retracement|Extension, label: str`
  - 自动标注柳玉东式关键价位（如"1.618扩展目标96188"）
- **Acceptance**: 单元测试验证回撤/扩展计算精度（误差<0.01%）

### TASK-004: 多空临界位标注器
- **Feature**: F-002
- **Files**: `quantflow/indicators/critical_level.py`
- **Description**: 标注多空临界位——突破/失守后浪型判定质变的价位
- **Spec**:
  - `CriticalLevelDetector(FactorBase)` — compute(df, wave_count: WaveCount) → CriticalLevels
  - 临界位规则:
    - W1 起点（跌破 → 推动浪失效）
    - W1 高点（突破 → W3 确认）
    - W3 高点（突破 → W5 推进）
    - W4 低点（跌破 → 浪型失效）
  - `CriticalLevels` dataclass: `levels: list[CriticalLevel]`, `active_bull_scenario: Scenario`, `active_bear_scenario: Scenario`
  - `CriticalLevel` dataclass: `price: float, level_type: CriticalLevelType, description: str, wave_ref: int`
  - 当 WaveCount 状态变更时自动重新计算 → G-002
  - `Scenario` dataclass: `direction: BULL|BEAR, trigger_level: CriticalLevel, targets: list[FibonacciLevel]`
- **Acceptance**: 单元测试验证临界位识别，场景切换逻辑正确

---

## Wave 2: 辅助验证 + 策略 + 信号风控 (4 tasks)

### TASK-005: 波浪通道线 + 背离检测器
- **Feature**: F-003
- **Files**: `quantflow/indicators/wave_channel.py`, `quantflow/indicators/divergence.py`
- **Description**: 波浪通道线判定浪5终点，MACD/成交量背离验证浪5末端和浪2/4底部
- **Spec**:
  - `WaveChannel(FactorBase)` — compute(df, wave_count: WaveCount) → ChannelResult
    - 连接 W1、W3 高点画上轨，平行于 W2 低点画下轨
    - `ChannelResult`: `upper_band: Series, lower_band: Series, w5_target: float|None`
  - `DivergenceDetector` — detect(wave_count: WaveCount) → DivergenceResult
    - 接口: detect(wave_count: WaveCount) → 强制浪级比较 → C-003
    - 顶背离: W5 价格新高但 MACD 未新高
    - 底背离: W2/W4 价格新低但 MACD 未新低
    - 成交量背离: W5 价格上涨但成交量萎缩
    - `DivergenceResult`: `divergences: list[Divergence]`, `bearish: bool, bullish: bool`
  - WaveChannel 上轨作为浪5终点辅助验证 → S-004
- **Acceptance**: 单元测试验证背离检测，通道线计算正确

### TASK-006: ElliottWaveStrategy 策略实现
- **Feature**: F-004
- **Files**: `quantflow/strategy/elliott_wave_strategy.py`
- **Description**: 继承 StrategyBase，实现 5 种浪段交易规则
- **Spec**:
  - `ElliottWaveStrategy(StrategyBase)` — on_init(ctx), on_bar(ctx, bar), generate_signals(df) → (entries, exits)
  - 5 种交易规则:
    1. **W2结束入场**: W2回撤至0.5/0.618 + 成交量萎缩 + MACD底背离
    2. **W3追势入场**: 突破W1高点 + 放量 + MACD张口
    3. **W4结束入场**: W4回撤至W3的0.382/0.5 + W2/W4交替 + 量缩
    4. **W5高点卖出**: 目标位 + MACD顶背离 + 量价背离 + 通道上轨
    5. **B浪结束卖出**: 反弹至A浪0.382/0.5/0.618 + 量小于A浪
  - generate_signals 返回 entries/exits 的 boolean Series
  - 所有规则参数暴露（回撤比率、入场条件等）→ S-003
  - 信号附带 `wave_context`: 当前浪型、置信度、触发规则
- **Acceptance**: 策略可实例化，on_bar 正确触发各浪段规则

### TASK-007: 波浪信号生成器 + 数浪失效规则
- **Feature**: F-005
- **Files**: `quantflow/signal/wave_signal_generator.py`, `quantflow/signal/wave_invalidation.py`
- **Description**: 波浪信号生成器桥接策略与风控，数浪失效规则触发硬/软止损
- **Spec**:
  - `WaveSignalGenerator` — 接收 ElliottWaveStrategy 的信号，附加风控元数据
    - 输出 `WaveSignal`: `direction, wave_label, confidence, critical_levels, invalidation_points`
  - `WaveInvalidationChecker` — 检查数浪失效条件:
    - 跌破前一同级别驱动浪起点 → 硬止损
    - W4深度进入W1区间 → 硬止损
    - 突破多空临界位且反向运行 → 硬止损
    - 连续三次止损 → 系统暂停信号
  - 软止损规则:
    - 移动止损: 盈利后上移至成本价或W2/W4低点
    - 时间止损: 预期时间内未达目标
    - 信号止损: MACD背离消失、成交量异常
- **Acceptance**: 失效规则正确触发，信号附带完整风控元数据

### TASK-008: 分批建仓/出场策略
- **Feature**: F-006
- **Files**: `quantflow/execution/scaling_position_sizer.py`
- **Description**: 扩展 PositionSizer，实现柳玉东式渐进加仓和分批出场
- **Spec**:
  - `ScalingPositionSizer` — 扩展现有 PositionSizer 接口
  - 建仓模型:
    - 试仓 10-15%: W2/W4 回撤至目标区域
    - 加仓 20-30%: 突破关键位 + W3 启动确认
    - 追仓 10-15%: W3 运行中途回调至短期均线
    - 最大仓位 50-60%（单品种）
  - 出场模型:
    - 第一出场 30%: 到达第一目标位
    - 第二出场 30%: 到达第二目标位或出现背离信号
    - 第三出场 40%: 浪型失效信号或止损触发
  - 输出 `PositionRequest` → RiskEngine 做最终权限控制 → G-003
  - 单笔风险 ≤2%，日最大亏损 ≤5%，月最大亏损 ≤15%
- **Acceptance**: 仓位计算符合柳玉东式渐进加仓模型，风控限额正确

---

## Wave 3: 数据对齐 + CLI + 配置 + 回测 (4 tasks)

### TASK-009: 多时间框架数据对齐
- **Feature**: F-007
- **Files**: `quantflow/data/mtf_aligner.py`
- **Description**: 多时间框架数据对齐——周线→4H→1H→15min 逐层展开
- **Spec**:
  - `MTFAligner` — align(symbol, timeframes=["1W","4H","1H","15m"]) → MTFData
  - `MTFData` dataclass: `primary: DataFrame, intermediate: DataFrame, minor: DataFrame, aligned_index: DatetimeIndex`
  - 使用 UTC 时间 + 滚动窗口（Q4）
  - 复用现有 fetcher 获取数据，MTFAligner 负责时间对齐和缺失值处理
  - 输出多时间框架 pivot 序列供浪型识别逐层分析 → S-002
- **Acceptance**: 对齐后时间戳一致，无未来数据泄漏

### TASK-010: elliott_wave.yaml 配置文件
- **Feature**: F-008
- **Files**: `quantflow/config/strategies/elliott_wave.yaml`
- **Description**: 波浪策略的完整 YAML 配置
- **Spec**:
  - zigzag 参数: thresholds, min_overlap
  - 浪型识别: analysis_mode, iron_law_enforcement
  - 斐波那契: retracement_ratios, extension_ratios
  - 交易规则: 各浪段回撤比率、入场条件开关
  - 仓位管理: trial_pct, add_pct, chase_pct, max_position_pct
  - 风控: single_risk_pct, daily_loss_limit, monthly_loss_limit
  - 回测: initial_capital, commission, slippage
- **Acceptance**: 配置加载无错误，所有参数可覆盖

### TASK-011: CLI 命令
- **Feature**: F-008
- **Files**: `quantflow/cli/main.py` (扩展)
- **Description**: 添加 `quantflow elliott-wave` 命令
- **Spec**:
  - `quantflow elliott-wave --symbol BTC/USDT --mode backtest|paper|live`
  - `quantflow elliott-wave --analyze --symbol BTC/USDT` — 输出当前浪型分析
  - 集成到现有 Typer CLI
- **Acceptance**: CLI 命令可执行，帮助信息正确

### TASK-012: VectorBT 回测集成 + 验证
- **Feature**: F-008
- **Files**: `quantflow/strategy/research/elliott_wave_backtest.py`, `tests/integration/test_elliott_wave.py`
- **Description**: 使用 VectorBT 回测验证波浪策略，集成防过拟合验证
- **Spec**:
  - 回测指标: 胜率≥55%, 盈亏比≥2:1, 最大回撤≤15%, 年化收益≥20%, 夏普比率≥1.5
  - 回测周期 ≥100 笔交易
  - 集成 CPCV + WFO 防过拟合验证
  - 参数敏感性测试: grid search 回撤比率（0.382/0.5/0.618）→ S-003
  - 集成测试: 端到端数据→指标→策略→信号→回测
- **Acceptance**: 回测指标达标，防过拟合验证通过，所有现有测试不回归

---

## Dependency Graph

```
TASK-001 (ZigZag) ──→ TASK-002 (WaveIdentifier) ──→ TASK-003 (Fibonacci)
                              │                           │
                              ├──────────────────────────→ TASK-004 (CriticalLevel)
                              │
                              ├─→ TASK-005 (Channel+Divergence)
                              │
                              └─→ TASK-006 (Strategy) ──→ TASK-007 (SignalGenerator)
                                                          │
                                      TASK-008 (Position) ┘
                                      TASK-009 (MTF) ──────→ TASK-012 (Backtest)
                                      TASK-010 (Config) ──→ TASK-012
                                      TASK-011 (CLI) ────→ TASK-012
```

## Key Decisions (from brainstorm)

| ID | Decision | Impact on Plan |
|----|----------|----------------|
| C-001 | W3铁律双模式 | TASK-002: IronLawValidator 支持 RETROSPECTIVE/PROGRESSIVE 模式 |
| C-002 | min_overlap>80% | TASK-001: 默认阈值设为 0.8，可配置 |
| C-003 | DivergenceDetector 接收 WaveCount | TASK-005: detect() 签名改为 (wave_count: WaveCount) |
| S-001 | WaveCount→IronLawValidator | TASK-002: WaveCount 作为 IronLawValidator 输入 |
| S-004 | WaveChannel 辅助浪5判定 | TASK-005: WaveChannel 输出 w5_target |
