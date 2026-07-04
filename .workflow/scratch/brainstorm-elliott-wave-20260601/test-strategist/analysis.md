# Test Strategist Analysis — 柳玉东波浪理论交易系统

> Contract: guidance-specification.md §test-strategist (decisions D1-D5, Q1-Q5)
> Owns: 测试覆盖策略、回测验证方法、参数敏感性测试、边界场景识别、防过拟合集成、测试数据fixtures、回归防护
> Does not own: 架构设计(system-architect)、波浪理论规则化(subject-matter-expert)、具体测试代码实现

## 1. Role Mandate (≤ 200 words)

作为 Test Strategist，我负责为 Elliott Wave 交易系统制定全面的测试策略。核心职责包括：定义浪型识别准确率的测试方法、设计回测验证管道、规划参数敏感性测试矩阵、识别边界场景和失效模式、集成 QuantFlow 现有防过拟合体系（CPCV/DSR/PBO/WFO）、创建历史波浪模式测试数据集、以及建立回归防护机制。我专注于测试策略和质量标准，不编写具体测试代码。测试策略 MUST 覆盖 F-001 至 F-008 全部 8 个功能模块，确保满足 §6 验收标准：胜率≥55%、盈亏比≥2:1、最大回撤≤15%、年化收益≥20%、夏普比率≥1.5、回测周期≥100笔交易。

## 2. Decision Digest

### Decisions
| ID | Feature | Stance | Constraints (RFC 2119) |
|----|---------|--------|------------------------|
| TS-01 | F-001 | ZigZag 参数敏感性测试 MUST 采用多参数交叉验证矩阵，覆盖 deviation 3%-10%、depth 5-20 范围 | MUST |
| TS-02 | F-001 | 浪型识别准确率测试 MUST 使用标注好的历史数据集，包含至少 50 个完整波浪周期 | MUST |
| TS-03 | F-002 | 斐波那契计算器精度测试 MUST 验证回撤位(0.236/0.382/0.5/0.618/0.786)和扩展位(1.0/1.272/1.618) | MUST |
| TS-04 | F-003 | 背离验证测试 MUST 覆盖 MACD 背离和成交量背离两种场景，每种至少 30 个样本 | MUST |
| TS-05 | F-004 | 策略回测 MUST 使用 VectorBT 框架，回测周期 MUST ≥100 笔交易 | MUST |
| TS-06 | F-005 | 数浪失效规则测试 MUST 验证硬止损和软止损两种场景的触发条件 | MUST |
| TS-07 | F-006 | 分批建仓测试 MUST 验证试仓(10-15%)、加仓(20-30%)、追仓(10-15%)的仓位比例 | MUST |
| TS-08 | F-007 | 多时间框架对齐测试 MUST 验证周线→4H→1H→15min 的数据一致性 | MUST |
| TS-09 | Cross | 防过拟合验证 MUST 集成 CPCV + DSR + PBO + WFO 全部四种方法 | MUST |
| TS-10 | Cross | 所有测试 SHOULD 标记 @pytest.mark.slow 或 @pytest.mark.live 以区分执行层级 | SHOULD |
| TS-11 | F-001 | 浪2/浪4 终点滞后判定测试 MUST 使用渐进确认模拟，验证概率标注更新机制 | MUST |
| TS-12 | F-004 | 回测验收标准 MUST 包含：胜率≥55%、盈亏比≥2:1、最大回撤≤15%、年化收益≥20%、夏普比率≥1.5 | MUST |

### Interfaces
| Name | Contract | Consumers |
|------|----------|-----------|
| WavePatternTestCase | `{symbol, timeframe, start_date, end_date, expected_waves: list[WaveLabel], confidence: float}` | F-001 浪型识别测试 |
| BacktestResult | `{trades: int, win_rate: float, profit_factor: float, max_drawdown: float, annual_return: float, sharpe: float}` | F-004/F-008 回测验证 |
| ZigZagParams | `{deviation: float, depth: int, backstep: int}` | F-001 参数敏感性测试 |
| FibonacciLevel | `{retracement: list[float], extension: list[float], tolerance: float}` | F-002 斐波那契测试 |
| ScalingPosition | `{trial_pct: float, add_pct: float, chase_pct: float, max_positions: int}` | F-006 分批建仓测试 |

### Cross-Cutting Positions
| Topic | Stance |
|-------|--------|
| Test Layers | 采用测试金字塔：单元测试 70%、集成测试 20%、端到端测试 10% |
| Coverage Targets | 核心模块覆盖率 MUST >70%，波浪识别引擎 MUST >85% |
| Risk-Based Prioritization | F-001 浪型识别为最高风险区，F-005 信号风控为高风险区，F-007 MTF对齐为中风险区 |
| Tooling | pytest + pytest-asyncio + pytest-cov + VectorBT 回测框架 |
| Anti-Overfitting | CPCV 组合交叉验证 + DSR 偏斜度修正 + PBO 过拟合概率 + WFO 步进前进优化 |
| Test Data | 历史波浪模式数据集 MUST 包含牛市、熊市、震荡市三种市场状态 |

### Findings Summary
| Slug | Title | Impact |
|------|-------|--------|
| zigzag-param-instability | ZigZag 参数不稳定性导致转折点漂移 | HIGH — 需要多参数共识机制 |
| wave2-wave4-lag | 浪2/浪4 终点判定滞后问题 | HIGH — 需要概率标注+渐进确认 |
| real-time-wave3-rule | 浪3"不能最短"铁律实时判定困难 | MEDIUM — 仅事后验证 |
| crypto-24-7-timeframe | 加密货币 24/7 交易导致时间框架定义模糊 | MEDIUM — 使用 UTC 滚动窗口 |

## 3. Cross-Cutting Foundations

### Test Layers

测试分层策略采用经典测试金字塔模型，确保测试效率与覆盖深度的平衡：

- **单元测试 (70%)**：针对单个函数/方法的逻辑正确性，包括 ZigZag 计算、斐波那契计算、浪型状态机转换、仓位比例计算等。单元测试 MUST 不依赖外部数据源，使用 mock/fixtures 隔离。
- **集成测试 (20%)**：验证模块间交互，包括 L1→L2 数据流、L2→L3 指标到策略、L3→L4 策略到信号、L4→L5 信号到执行。集成测试 MUST 使用测试数据库和模拟 Gateway。
- **端到端测试 (10%)**：完整交易流程验证，从数据获取到订单执行。端到端测试 MUST 标记 `@pytest.mark.live`，仅在 CI/CD 特定阶段或手动触发执行。

### Coverage Targets

覆盖率目标基于风险评估和业务关键性设定：

| 模块 | 目标覆盖率 | 理由 |
|------|-----------|------|
| quantflow/indicators/elliott_wave.py | ≥85% | 核心浪型识别逻辑，错误直接影响交易决策 |
| quantflow/strategy/elliott_wave.py | ≥80% | 策略信号生成，影响盈亏 |
| quantflow/signal/wave_signal.py | ≥75% | 信号生成和失效规则 |
| quantflow/execution/scaling_position.py | ≥70% | 仓位管理，影响风险控制 |
| quantflow/data/mtf_aligner.py | ≥70% | 多时间框架对齐 |
| 其他模块 | ≥60% | 标准要求 |

### Risk-Based Prioritization

基于风险评估的测试优先级排序：

**高风险区 (P0)**：
- F-001 ZigZag 转折点检测和浪型识别 — 错误会级联影响所有下游模块
- F-005 数浪失效规则和止损逻辑 — 直接影响资金安全

**中高风险区 (P1)**：
- F-004 ElliottWaveStrategy 信号生成 — 影响交易决策质量
- F-006 分批建仓/出场策略 — 影响仓位风险

**中风险区 (P2)**：
- F-002 斐波那契计算器 — 计算错误影响目标价
- F-003 波浪通道和背离验证 — 辅助确认信号
- F-007 多时间框架对齐 — 数据一致性问题

**低风险区 (P3)**：
- F-008 CLI 和配置 — 用户界面层，错误易发现

### Tooling

测试工具栈与 QuantFlow 现有体系保持一致：

- **pytest**：核心测试框架，支持参数化、fixtures、markers
- **pytest-asyncio**：异步测试支持，用于测试 async 事件处理
- **pytest-cov**：覆盖率报告生成
- **pytest-mock**：Mock 和 spy 功能
- **VectorBT**：回测框架，用于策略验证
- **hypothesis**：属性测试，用于边界场景发现
- **freezegun**：时间控制，用于测试特定时间点的波浪判定

## 4. File Index

| File | Type | Feature | Headings |
|------|------|---------|----------|
| [analysis-F-001-zigzag-wave-identifier.md](analysis-F-001-zigzag-wave-identifier.md) | feature | F-001 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-002-fibonacci-critical-level.md](analysis-F-002-fibonacci-critical-level.md) | feature | F-002 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-003-wave-channel-divergence.md](analysis-F-003-wave-channel-divergence.md) | feature | F-003 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-004-elliott-wave-strategy.md](analysis-F-004-elliott-wave-strategy.md) | feature | F-004 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-005-wave-signal-risk.md](analysis-F-005-wave-signal-risk.md) | feature | F-005 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-006-scaling-position.md](analysis-F-006-scaling-position.md) | feature | F-006 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-007-multi-timeframe-align.md](analysis-F-007-multi-timeframe-align.md) | feature | F-007 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |
| [analysis-F-008-cli-config-backtest.md](analysis-F-008-cli-config-backtest.md) | feature | F-008 | Architecture, Interface Contract, Constraints, Test Approach, TODOs |

## 5. Outstanding TODOs

- [ ] 创建历史波浪模式标注数据集（BTC/USDT 2020-2024，至少 50 个完整周期）
- [ ] 定义 ZigZag 参数敏感性测试矩阵的具体参数组合
- [ ] 设计浪型识别准确率的评估指标和计算方法
- [ ] 编写防过拟合验证管道的测试用例模板
- [ ] 确定多时间框架对齐测试的时间窗口边界条件
- [ ] 建立回测结果与实盘表现的偏差监控机制
- [ ] 设计回归测试套件的 CI/CD 集成方案
