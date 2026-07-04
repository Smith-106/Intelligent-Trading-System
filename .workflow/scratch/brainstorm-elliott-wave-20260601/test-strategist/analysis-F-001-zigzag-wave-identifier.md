# F-001 — ZigZag转折点检测 + 浪型识别引擎

> Role: test-strategist | Related decisions: TS-01, TS-02, TS-11

## Architecture

ZigZag 转折点检测和浪型识别引擎是整个 Elliott Wave 系统的基础模块（L2 指标层），其测试架构 MUST 分为三层：

1. **ZigZag 算法层**：测试转折点检测算法在不同参数下的行为
2. **浪型识别层**：测试三大铁律验证逻辑（浪2不破浪1起点、浪3不能最短、浪4不进浪1区域）
3. **渐进确认层**：测试概率标注和回溯更新机制

测试模块位于 `tests/unit/indicators/test_elliott_wave.py` 和 `tests/integration/test_wave_identification.py`。

## Interface Contract

ZigZag 和浪型识别引擎暴露以下测试接口：

- `compute_zigzag(df, deviation, depth, backstep) -> pd.DataFrame` — 输入 OHLCV 数据，输出转折点标记
- `identify_waves(pivots, rules=['three_iron_laws']) -> list[WavePattern]` — 输入转折点序列，输出浪型结构
- `validate_wave_rules(wave_pattern) -> ValidationResult` — 验证三大铁律
- `update_wave_probabilities(current_waves, new_bar) -> list[WavePattern]` — 渐进确认更新

测试 MUST 通过这些接口进行，不依赖内部实现细节。

## Constraints (RFC 2119)

- ZigZag 参数敏感性测试 MUST 覆盖 deviation 范围 3%-10%（步长 1%），depth 范围 5-20（步长 5）
- 浪型识别准确率测试 MUST 使用人工标注的历史数据集，包含至少 50 个完整波浪周期
- 三大铁律验证测试 MUST 包含：合法浪型（通过）、非法浪型（拒绝）、边界浪型（需判定）
- 浪2/浪4 终点滞后判定测试 MUST 模拟逐根K线输入，验证概率标注的渐进更新
- 浪3"不能最短"铁律实时判定 MUST NOT 在浪3运行中强制执行，仅事后验证
- ZigZag 转折点检测 MUST 在相同参数和数据下产生确定性结果
- 多参数 ZigZag 交叉验证 MUST 计算转折点共识度（≥2/3 参数组合一致的转折点为高置信）

## Test Approach

### 单元测试

**ZigZag 算法测试**：
- 给定已知转折点的合成价格序列，验证检测到的转折点与预期一致
- 参数化测试：使用 `@pytest.mark.parametrize` 覆盖 deviation/depth/backstep 组合
- 边界场景：单边上涨（无转折）、V 形反转（单转折）、锯齿形（密集转折）
- 噪声容忍度测试：在清晰趋势中添加不同水平的噪声，验证转折点稳定性

**三大铁律验证测试**：
- 浪2回撤测试：浪2终点 MUST 不低于浪1起点（推动浪）—— 合法/非法各 5 个 case
- 浪3长度测试：浪3 MUST 不是最短的推动浪 —— 覆盖浪3最长、次长、最短三种情况
- 浪4重叠测试：浪4 MUST 不进入浪1区域 —— 覆盖重叠/不重叠/刚好触碰三种情况
- 三条铁律的组合验证：同时违反多条规则时的处理优先级

**浪型识别状态机测试**：
- 状态转换合法性：枚举状态机中所有合法和非法状态转换
- 不完整浪型处理：1浪完成→2浪进行中→3浪未开始的中间状态
- 调整浪识别：A-B-C 结构和复杂调整浪（三角形、锯齿形）的区分

### 集成测试

**渐进确认模拟**：
- 模拟实时数据流，逐根K线输入，验证浪型标注的概率变化
- 回溯修正场景：当新数据导致前期浪型判定改变时，验证更新机制的正确性
- 延迟确认场景：浪2/浪4 终点只能在后续浪确认后回溯标注

**参数敏感性矩阵测试**：
- 生成多参数组合下的转折点集合
- 计算共识转折点（≥2/3 参数组合一致）
- 验证共识转折点与人工标注的一致性
- 测量参数变化对转折点位置的影响幅度

### 测试数据 Fixtures

```
fixtures/
├── zigzag_synthetic/       # 合成数据（已知转折点）
│   ├── clean_trend.json    # 清晰趋势
│   ├── noisy_trend.json    # 含噪声趋势
│   └── sideways.json       # 横盘震荡
├── wave_labeled/           # 人工标注数据
│   ├── btc_2020_bull.json  # 2020 牛市
│   ├── btc_2021_cycle.json # 2021 完整周期
│   ├── btc_2022_bear.json  # 2022 熊市
│   └── eth_2023_recovery.json
└── iron_law_cases/         # 三大铁律测试用例
    ├── valid_impulse.json
    ├── invalid_wave2.json
    ├── invalid_wave3.json
    └── invalid_wave4.json
```

## TODOs

- [ ] 收集并标注 BTC/USDT 2020-2024 历史数据中的完整波浪周期
- [ ] 定义转折点位置误差的容忍标准（如 ±2 根K线）
- [ ] 设计共识转折点的置信度评分算法
- [ ] 确定浪型识别准确率的基线值（target: ≥80% 共识转折点匹配）
- [ ] 建立参数敏感性测试的自动化报告模板
- [ ] 参考 [F-005](analysis-F-005-wave-signal-risk.md) 确认数浪失效对浪型识别的影响
