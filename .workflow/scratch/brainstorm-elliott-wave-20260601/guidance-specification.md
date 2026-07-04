# Brainstorm Guidance Specification — 柳玉东波浪理论交易系统

## §1 核心决策

| # | 决策 | 选项 | 选择 | 理由 |
|---|------|------|------|------|
| D1 | 集成方式 | 独立系统 / 集成到QuantFlow | 集成到QuantFlow | 复用现有六层架构+基础设施 |
| D2 | 量化方式 | 纯规则引擎 / 规则+ML混合 / ML为主 | 纯规则引擎 | 可回测可验证，解决"千人千浪" |
| D3 | 浪型表示 | 枚举状态机 / 概率分布 / 模式匹配 | 枚举状态机 | 与三大铁律规则逻辑一致 |
| D4 | 多时间框架 | 独立数据管线 / 复用现有fetcher | 复用+扩展 | L1层已有fetcher，仅需MTF对齐逻辑 |
| D5 | 仓位模型 | 独立仓位管理器 / 扩展PositionSizer | 扩展PositionSizer | 与风控体系解耦，复用现有接口 |

## §2 关键问题

| # | 问题 | 风险 | 建议方案 |
|---|------|------|---------|
| Q1 | ZigZag参数敏感性——不同参数标记不同转折点 | 浪型识别不稳定 | 多参数ZigZag交叉验证，取共识转折点 |
| Q2 | 浪2/浪4终点判定滞后——只能在后续浪确认后回溯 | 实时交易中信号延迟 | 采用概率标注+渐进确认，随新数据更新 |
| Q3 | 浪3"不能最短"铁律在实时中难以判定 | 误判 | 浪3运行中不强制此铁律，仅事后验证+调整 |
| Q4 | 加密货币24/7交易——日线/周线定义模糊 | 时间框架对齐错误 | 使用UTC时间+滚动窗口，而非自然日 |
| Q5 | 多空临界位动态变化 | 止损位漂移 | 临界位随浪型更新动态调整，通知机制 |

## §3 非目标

- ML/深度学习浪型识别
- A股实盘扩展
- 高频交易支持
- Web UI 波浪可视化
- 周期窗口测算（时间维度预测）
- 交易日志/复盘模板

## §4 术语定义

- **WavePattern**: 推动浪(1-5)或调整浪(A-B-C)的完整结构标识
- **CriticalLevel**: 多空临界位——突破或失守后浪型判定质变的价位
- **FibonacciLevel**: 斐波那契回撤/扩展位，用于目标价和入场区计算
- **ZigZag**: 自动标记价格转折点的指标，辅助浪型识别
- **WaveChannel**: 连接浪1、3高点画平行通道，判定浪5终点
- **Divergence**: MACD/成交量与价格的背离信号，验证浪5末端
- **WaveInvalidation**: 数浪失效——关键价位突破后承认当前方案失效
- **ScalingPosition**: 分批建仓——试仓→加仓→追仓的渐进仓位模型
- **MultiTimeframe**: 多时间框架分析——周线→4H→1H→15min逐层展开
- **StrategyBase**: QuantFlow 策略基类接口

## §5 架构约束

1. 集成到 QuantFlow 六层架构：L1 数据 → L2 指标 → L3 策略 → L4 信号风控 → L5 执行 → L6 监控
2. 层间单向依赖，低层不依赖高层
3. 接口驱动（Protocol/ABC），内部实现可替换
4. 配置外置（YAML 驱动），策略参数全部 elliott_wave.yaml
5. 事件解耦，策略不直接调用 Gateway
6. 回测-实盘一致，TradingSession 统一 backtest/paper/live

## §6 验收标准

1. ZigZag 指标自动标记转折点，浪型识别引擎通过三大铁律验证
2. 斐波那契回撤/扩展计算器输出精确价位，多空临界位标注清晰
3. ElliottWaveStrategy 继承 StrategyBase，5种浪段交易规则完整编码
4. 分批建仓/出场策略集成到 PositionSizer
5. 多时间框架数据对齐正确（周线→4H→1H→15min）
6. VectorBT 回测通过：胜率≥55%，盈亏比≥2:1
7. 所有现有测试不回归

## §7 参考来源

- 波浪理论在实战中常见的技术误区与正确数浪方法 - 约投顾
- 什么是波浪理论？在A股实战中如何正确划分上涨与下跌周期 - 约投顾
- 艾略特波浪分形系统 - FMZ量化平台
- 波浪理论第12章操作法则－波浪理论实战篇 - Fish佳瑜
- 艾略特波浪理论交易指南：波浪形态交易完全手册 - Aurra Markets

## §8 角色分配

| 角色 | 关注点 | 关键问题 |
|------|--------|---------|
| **system-architect** | 六层架构集成、数据流、接口设计、浪型状态机 | D1集成方式、D3浪型表示、§5架构约束 |
| **subject-matter-expert** | 波浪理论规则化、三大铁律量化、柳玉东特色实现 | D2量化方式、Q1-Q5关键问题、§6验收标准 |
| **test-strategist** | 回测验证、浪型识别准确率、防过拟合、可测试性 | Q1参数敏感性、Q2滞后判定、§6回测指标 |

## §9 决议协议

- 每个决策需要 ≥2/3 角色共识才能确认
- 冲突由 subject-matter-expert 在波浪理论规则层面裁决
- 架构冲突由 system-architect 裁决
- 测试策略冲突由 test-strategist 裁决

## §10 时间预算

- 角色分析：每角色 1 份 analysis.md，覆盖其关键问题
- 跨角色复审：1 份 review，识别冲突/缺口/协同
- 决议回流：更新 guidance-specification §1 + §2

## §11 输出结构

```
.workflow/scratch/brainstorm-elliott-wave-20260601/
├── guidance-specification.md    (本文件)
├── system-architect/
│   └── analysis.md
├── subject-matter-expert/
│   └── analysis.md
├── test-strategist/
│   └── analysis.md
└── cross-role-review.md
```

## §12 决议回流

### 已确认决策变更

| ID | 原决策 | 变更后 | 裁决依据 |
|----|--------|--------|---------|
| C-001 | W3"不能最短"铁律实时强制执行 | 双模式：回顾模式强制、渐进模式仅检查不拒绝分类 | Q2滞后判定+Q3实时困难，需平衡严谨与可用性 |
| C-002 | ZigZag共识重叠阈值默认67% | 调整为>80%重叠，min_overlap参数可配置 | SME建议提高准确率，SA同意设为可配置 |
| C-003 | DivergenceDetector.detect(df, pivots) | DivergenceDetector.detect(wave_count: WaveCount) 强制浪级比较 | SME要求W5vsW3浪级比较，SA接口改为WaveCount驱动 |

### 新增关键问题

| ID | 问题 | 风险 | 建议方案 |
|----|------|------|---------|
| Q6 | 回顾模式vs渐进模式切换时机 | 不当切换导致规则执行不一致 | 浪型确认后自动切换：子浪完成→回顾模式，新数据到达→渐进模式 |
| Q7 | min_overlap>80%可能导致部分品种无共识转折点 | 交易信号缺失 | 提供fallback：无共识时使用单ZigZag+降低置信度标记 |

### 跨角色协同点

| ID | 协同 | 集成建议 |
|----|------|---------|
| S-001 | SA的WaveCount状态机 + SME的三大铁律验证器 | WaveCount提供状态上下文，IronLawValidator消费WaveCount做规则校验 |
| S-002 | SA的MTF对齐层 + SME的多时间框架浪型嵌套 | MTF对齐输出多时间框架pivot序列，供浪型识别逐层分析 |
| S-003 | SME的波浪交易规则 + TS的参数敏感性测试 | 每条规则暴露参数（如回撤比率0.382/0.5/0.618），TS做grid search验证 |
| S-004 | SA的WaveChannel + SME的浪5终点判定 | WaveChannel上轨作为浪5终点的辅助验证条件 |

### 缺口补充

| ID | 缺口 | 补充方案 |
|----|------|---------|
| G-001 | ZigZag→WaveIdentifier数据流未定义 | SA补充：ZigZag输出PivotSequence，WaveIdentifier消费PivotSequence |
| G-002 | CriticalLevel更新触发机制未定义 | SME补充：当WaveCount状态变更时，CriticalLevel自动重新计算 |
| G-003 | ScalingPosition与RiskEngine的交互未定义 | SA补充：ScalingPosition输出PositionRequest，RiskEngine做最终权限控制 |
