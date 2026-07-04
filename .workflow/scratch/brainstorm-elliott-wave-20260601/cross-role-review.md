# Cross-Role Review — 柳玉东波浪理论交易系统

## Conflicts (3)

### C-001: W3"不能最短"铁律——实时强制 vs 仅事后验证
- **Source**: subject-matter-expert vs system-architect
- **SME立场**: 三大铁律无条件执行，W3违反立即拒绝浪型
- **SA立场**: 实时浪3运行中W3无法判定，仅事后验证
- **Resolution**: 双模式——回顾模式强制W3、渐进模式仅检查不拒绝分类
- **Rationale**: Q2滞后判定+Q3实时困难，需平衡严谨与可用性

### C-002: ZigZag共识重叠阈值——80% vs 67%
- **Source**: subject-matter-expert vs system-architect
- **SME立场**: >80%重叠确保准确率
- **SA立场**: min_overlap默认2/3=67%
- **Resolution**: 调整默认为>80%，min_overlap参数可配置
- **Rationale**: 提高准确率优先，但允许品种差异通过配置调整

### C-003: 背离比较对象——浪级转折点 vs 任意转折点
- **Source**: subject-matter-expert vs system-architect
- **SME立场**: 必须W5vsW3浪级比较，任意pivots无意义
- **SA立场**: DivergenceDetector.detect(df, pivots)通用接口
- **Resolution**: 接口改为DivergenceDetector.detect(wave_count: WaveCount)，强制浪级比较
- **Rationale**: 波浪理论背离验证必须基于浪级，通用接口会导致误用

## Gaps (3)

### G-001: ZigZag→WaveIdentifier数据流未定义
- **Source**: system-architect 定义了ZigZag和WaveIdentifier但未连接
- **Resolution**: ZigZag输出PivotSequence，WaveIdentifier消费PivotSequence

### G-002: CriticalLevel更新触发机制未定义
- **Source**: subject-matter-expert 定义了CriticalLevel但未说明何时更新
- **Resolution**: 当WaveCount状态变更时，CriticalLevel自动重新计算

### G-003: ScalingPosition与RiskEngine的交互未定义
- **Source**: system-architect 定义了两者但未定义交互协议
- **Resolution**: ScalingPosition输出PositionRequest，RiskEngine做最终权限控制

## Synergies (4)

### S-001: WaveCount状态机 × 三大铁律验证器
- **Roles**: system-architect + subject-matter-expert
- **Integration**: WaveCount提供状态上下文，IronLawValidator消费WaveCount做规则校验

### S-002: MTF对齐层 × 多时间框架浪型嵌套
- **Roles**: system-architect + subject-matter-expert
- **Integration**: MTF对齐输出多时间框架pivot序列，供浪型识别逐层分析

### S-003: 波浪交易规则 × 参数敏感性测试
- **Roles**: subject-matter-expert + test-strategist
- **Integration**: 每条规则暴露参数（回撤比率0.382/0.5/0.618），TS做grid search验证

### S-004: WaveChannel × 浪5终点判定
- **Roles**: system-architect + subject-matter-expert
- **Integration**: WaveChannel上轨作为浪5终点的辅助验证条件
