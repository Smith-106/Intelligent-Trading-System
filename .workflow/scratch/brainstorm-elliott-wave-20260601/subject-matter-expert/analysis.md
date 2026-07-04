# Subject Matter Expert Analysis — 柳玉东波浪理论交易系统

> Contract: guidance-specification.md §subject-matter-expert (decisions D2, Q1-Q5)
> Owns: 波浪理论规则化、三大铁律量化、斐波那契计算、临界位标注、各浪段交易规则、背离验证、数浪失效规则
> Does not own: 六层架构集成、数据流设计、接口定义、回测验证策略、防过拟合

## 1. Role Mandate (≤ 200 words)

作为波浪理论领域专家，我负责将艾略特波浪理论的核心规则转化为可执行的量化逻辑。我的职责包括：三大铁律的形式化编码（不可违背的硬约束）、斐波那契比率计算与临界位标注、五种浪段交易规则的精确定义、背离检测与成交量验证、以及数浪失效规则的制定。我确保所有波浪相关逻辑符合波浪理论的本源原则，同时适应加密货币 24/7 交易的特殊性。我不负责架构设计、数据流实现、回测框架或防过拟合验证——这些由 system-architect 和 test-strategist 负责。我的裁决在波浪理论规则层面具有最高优先级。

## 2. Decision Digest

### Decisions
| ID | Feature | Stance | Constraints (RFC 2119) |
|----|---------|--------|------------------------|
| SME-01 | F-001 | 三大铁律必须作为硬布尔谓词强制执行，不允许容差覆盖 | Iron Law violations MUST reject wave classification unconditionally |
| SME-02 | F-001 | 多参数 ZigZag 共识机制解决参数敏感性问题 | Consensus pivots MUST have > 80% overlap across threshold range |
| SME-03 | F-002 | 斐波那契计算必须区分上升浪与下降浪方向 | Down-wave retracement levels MUST ascend from wave_end |
| SME-04 | F-002 | 临界位随浪型更新动态调整，触发失效事件 | Critical levels MUST be recomputed on wave count update |
| SME-05 | F-003 | MACD 背离比较 W5 与 W3 的柱状图值，非 W1 | Divergence MUST compare histogram at W5 vs W3 peaks |
| SME-06 | F-004 | 五种浪段交易规则各自独立实现为可测试方法 | Each rule MUST be a distinct method with independent tests |
| SME-07 | F-005 | 硬止损设在铁律边界，不可向不利方向移动 | Hard stop at iron law boundary MUST NOT be moved against position |
| SME-08 | F-006 | 分批建仓总仓位不得超过配置的最大仓位比例 | Total cumulative position MUST NOT exceed max_position_pct |
| SME-09 | F-007 | 加密货币时间框架使用 UTC 固定边界，非自然日 | All bar boundaries MUST be anchored to UTC |
| SME-10 | F-008 | 回测与实盘使用相同的 generate_signals() 方法 | No separate backtest-only logic is permitted |

### Interfaces
| Name | Contract | Consumers |
|------|----------|-----------|
| `classify_impulse_strict()` | `pivots -> Optional[pd.DataFrame]` with iron laws | F-004 Strategy, F-005 Signal Generator |
| `identify_critical_levels()` | `wave_labels, current_price -> list[CriticalLevel]` | F-005 Invalidation Engine |
| `detect_divergence()` | `close, macd_hist, volume, wave_pivots -> pd.Series` | F-004 Strategy |
| `plan_scaling()` | `Signal, WaveContext -> ScalingPlan` | F-006 Position Sizer |
| `propagate_wave_context()` | `wave_labels[TF] -> dict[str, str]` | F-007 MTF Manager |

### Cross-Cutting Positions
| Topic | Stance |
|-------|--------|
| 三大铁律地位 | 不可违背的硬约束，优先级高于所有斐波那契比率检查 |
| 实时判定滞后 | 采用概率标注（tentative/probable/confirmed），仅 probable 及以上触发信号 |
| 参数敏感性 | 多参数共识机制，单参数结果不可信 |
| 24/7 时间框架 | UTC 固定边界，滚动窗口替代自然日 |
| 临界位动态性 | 随浪型更新重算，失效时触发事件通知 |

### Findings Summary
| Slug | Title | Impact |
|------|-------|--------|
| iron-law-2-missing | 现有代码缺失铁律2（W3不能最短）的强制检查 | HIGH — 可能接受无效浪型 |
| fib-direction-bug | 斐波那契计算对上升/下降浪使用相同公式 | MEDIUM — 下降浪回撤位计算错误 |
| divergence-wave-degree | 现有背离检测比较相邻转折点而非浪级转折点 | MEDIUM — 可能产生虚假背离信号 |

## 3. Cross-Cutting Foundations

### Pitfall Taxonomy

波浪理论量化实现的主要陷阱：

1. **铁律遗漏**：现有代码未完整实现三大铁律，特别是"浪3不能最短"完全缺失。这会导致接受无效的推动浪分类，产生错误的交易信号。SME-01 强制要求所有铁律作为硬约束。

2. **参数敏感性陷阱**：ZigZag 阈值选择直接影响转折点识别，不同参数产生截然不同的浪型。单参数方案不可靠。SME-02 采用多参数共识机制解决。

3. **实时判定悖论**：浪2/浪4终点只能在后续浪确认后回溯判定，但交易需要实时决策。引入概率标注体系，tentative 状态不触发信号。

4. **方向性计算错误**：斐波那契回撤位计算需要区分上升浪与下降浪，现有代码使用相同公式。SME-03 明确要求方向性计算。

5. **浪级混淆**：背离检测应在浪级转折点进行，而非任意相邻转折点。SME-05 明确 W5 背离比较对象是 W3 峰值。

### Pattern Fingerprints

柳玉东分析风格的量化指纹：

- **精确价位标注**：如"突破91233，目标96188"——对应斐波那契扩展位的精确计算
- **多空临界位**：突破/失守关键价位改变浪型判定——对应 CriticalLevel 的 invalidates 字段
- **成交量验证**：W3 放量突破、W5 量缩背离——对应 divergence 检测的 volume 组件
- **渐进确认**：不一次性确定浪型，随新数据更新——对应 tentative/probable/confirmed 状态机

### Domain-Silence Decisions

波浪理论未明确规定的领域，需要量化实现时做出决策：

1. **加密货币时间框架定义**：传统波浪理论基于自然日/周，加密货币 24/7 交易需要重新定义。决策：使用 UTC 固定边界（SME-09）。

2. **铁律违反后的重分类优先级**：当推动浪被铁律否决后，应尝试何种替代分类？决策：优先尝试对角三角形，其次复杂调整浪。

3. **多时间框架冲突解决**：低时间框架浪型与高时间框架矛盾时如何处理？决策：低时间框架必须服从高时间框架，重分类为子浪（F-007 约束）。

4. **斐波那契容差范围**：理论未规定容差，实践中需要量化标准。决策：默认 ±15%，可通过 YAML 配置。

### Differentiation Thesis

本系统与现有波浪量化方案的区别：

| 维度 | 本系统 | 典型方案 |
|------|--------|----------|
| 铁律执行 | 硬约束，无条件拒绝 | 软约束，允许容差 |
| 参数敏感性 | 多参数共识 | 单参数依赖 |
| 实时判定 | 概率状态机 | 二元判定 |
| 临界位管理 | 动态更新+失效事件 | 静态计算 |
| 仓位策略 | 分批建仓（试仓/加仓/追仓） | 单次建仓 |

### Crosswalk

与 QuantFlow 现有模块的对照：

| 波浪概念 | QuantFlow 对应 | 集成方式 |
|----------|----------------|----------|
| WavePattern | L2 indicators/elliott_wave.py | 扩展现有模块 |
| CriticalLevel | L4 signal/generator.py | 新增 WaveSignalGenerator |
| ScalingPosition | L4 signal/position_sizer.py | 扩展 PositionSizer |
| MultiTimeframe | L1 data/fetcher.py | 扩展 Fetcher + 新增 MTFDataManager |
| WaveInvalidation | L4 signal/risk_engine.py | 集成到现有 RiskEngine |

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

1. **铁律2实现**：在 `classify_impulse_strict()` 中添加 W3 不能最短的检查逻辑
2. **斐波那契方向修复**：修正 `compute_fibonacci_levels()` 对下降浪的计算
3. **浪级背离检测**：重构 `wave_momentum_divergence()` 以浪级转折点为比较对象
4. **概率状态机定义**：明确 tentative/probable/confirmed 的判定阈值
5. **重分类协议**：定义铁律违反后的替代浪型尝试顺序
6. **WaveState 数据结构**：设计跟踪活跃浪型、临界位、仓位关联的状态对象
7. **失效事件模式**：定义供执行层响应的失效事件 schema
8. **MTF 存储方案**：确定如何在现有 Parquet 分区方案中存储多时间框架数据
9. **Rich 表格布局**：设计 CLI analyze 和 fib-levels 命令的输出格式
10. **每规则指标计算**：实现回测中按五种浪段规则分别统计胜率和盈亏比
