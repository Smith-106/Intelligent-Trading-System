# F-007 — 多时间框架数据对齐

> Role: test-strategist | Related decisions: TS-08

## Architecture

多时间框架数据对齐位于 L1 数据层，为策略层提供周线→4H→1H→15min 的逐层展开数据。测试架构 MUST 分为：

1. **数据获取层**：验证不同时间框架数据的正确获取
2. **时间对齐层**：验证不同时间框架K线的时间戳对齐
3. **浪型传递层**：验证高时间框架浪型向低时间框架的传递
4. **一致性验证层**：验证多时间框架浪型判定的一致性

测试模块位于 `tests/unit/data/test_mtf_aligner.py` 和 `tests/integration/test_mtf_alignment.py`。

## Interface Contract

多时间框架对齐暴露以下测试接口：

- `fetch_mtf_data(symbol, timeframes=['1W','4H','1H','15m']) -> dict[str, pd.DataFrame]` — 获取多时间框架数据
- `align_timeframes(data_dict) -> AlignedData` — 对齐时间框架
- `propagate_wave_pattern(parent_pattern, child_timeframe) -> list[WavePattern]` — 传递浪型到子时间框架
- `validate_consistency(patterns_dict) -> ConsistencyResult` — 验证多时间框架一致性

## Constraints (RFC 2119)

- 时间框架对齐 MUST 使用 UTC 时间戳，不使用本地时间
- 加密货币 24/7 交易场景下，周线 MUST 使用 UTC 周一 00:00 作为起始点
- K线聚合 MUST 确保子时间框架K线完整覆盖父时间框架K线
- 4H K线 MUST 由 1H K线聚合，1H K线 MUST 由 15min K线聚合
- 浪型传递 MUST 遵循"大管小"原则：周线浪型约束 4H 浪型
- 多时间框架浪型冲突时，MUST 以高时间框架为准
- 数据对齐 MUST 处理缺失K线场景（交易所维护、数据延迟）

## Test Approach

### 单元测试

**时间对齐测试**：
- 给定 15min K线数据，验证聚合为 1H/4H/1W K线的正确性
- UTC 时间边界测试：验证周线起始点为 UTC 周一 00:00
- 时区转换测试：验证不同时区输入数据的正确对齐
- 缺失K线处理：验证缺失K线不影响聚合结果（使用可用数据聚合）

**K线聚合精度测试**：
- OHLCV 聚合规则验证：Open=首根Open、High=最高High、Low=最低Low、Close=末根Close、Volume=总和
- 边界场景：4H K线仅包含 3 根 1H K线（缺失 1 根）时的处理
- 跨日/跨周K线的正确归属

**浪型传递测试**：
- 周线推动浪 → 4H 子浪结构验证
- 4H 浪3 → 1H 子浪结构验证
- 1H 浪5 → 15min 子浪结构验证
- 传递一致性：子时间框架浪型 MUST 不违反父时间框架浪型约束

### 集成测试

**多时间框架一致性验证**：
- 给定 BTC/USDT 多时间框架历史数据，验证浪型判定的一致性
- 冲突场景：4H 判定为浪3延伸，但周线已进入浪5 → 以周线为准
- 对齐延迟场景：4H 数据已更新但 1H 数据延迟 → 等待或使用缓存数据

**数据流集成测试**：
- CCXT fetcher → Redis Cache → MTF Aligner → Strategy 完整链路
- 验证数据从获取到策略消费的端到端正确性
- 标记 `@pytest.mark.slow`

### 测试数据 Fixtures

```
fixtures/
├── mtf_data/
│   ├── btc_15m_sample.json    # 15min K线样本
│   ├── btc_1h_sample.json     # 1H K线样本
│   ├── btc_4h_sample.json     # 4H K线样本
│   └── btc_1w_sample.json     # 周线样本
├── alignment_cases/
│   ├── perfect_alignment.json # 完美对齐
│   ├── missing_bars.json      # 缺失K线
│   └── timezone_edge.json     # 时区边界
└── consistency_cases/
    ├── consistent_waves.json  # 一致浪型
    └── conflicting_waves.json # 冲突浪型
```

## TODOs

- [ ] 确定缺失K线的容忍阈值（连续缺失多少根后标记数据不可靠）
- [ ] 设计多时间框架浪型冲突的自动解决策略
- [ ] 定义数据对齐延迟的最大容忍时间
- [ ] 参考 [F-001](analysis-F-001-zigzag-wave-identifier.md) 确认浪型识别在多时间框架下的参数差异
