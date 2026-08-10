# W17 — 波浪理论：使用边界与防 repaint

**Date**: 2026-08-10  
**Source audit**: wave-audit (teammate explorer)  
**Related**: [w17-small-team-edge.md](./w17-small-team-edge.md) · knowhow: 波浪纯规则引擎集成六层  

---

## 1. 库存（research-grade vs toy）

### Research-grade 主路径

| 模块 | 角色 | 锚点 |
|------|------|------|
| `zigzag.py` | 多阈值共识 pivot（0.03–0.15，`min_overlap_ratio=0.8`） | `ZigZagIndicator` / `compute_pivot_sequence` |
| `wave_identifier.py` | 铁律 + RETROSPECTIVE / PROGRESSIVE | `WaveIdentifier` |
| `wave_models.py` | `WavePattern` / `WaveSegment` / `WaveCount` | 模型 |
| `fibonacci.py` / `critical_level.py` / `wave_channel.py` | 目标与失效位 | 投影/水平 |
| `divergence.py` | MACD/RSI/volume 背离（wave-degree） | 有参考点嫌疑 bug |
| `strategy/elliott_wave_strategy.py` | `LiuYudongWaveStrategy` 五规则 + CORR-019 增量窗 | 主策略 |
| `signal/wave_signal_generator.py` | `WaveSignal` enrich + `WaveInvalidationChecker` | **策略侧疑似未接线** |

### Toy / 遗留轨

| 模块 | 问题 |
|------|------|
| `indicators/elliott_wave.py` | 单阈值；整表最后 5 pivot 标注 |
| `strategy/templates/elliott_wave.py` | 向量化玩具；**SHORT 无 profit-target**（LONG-only TP） |

**边界**：研究与 paper 应以 **LiuYudong 路径** 为准；模板轨要么修要么标记 deprecated。

---

## 2. 防未来 / repaint 风险（按严重度）

### R1 — In-progress 末 pivot 可翻转（固有 + 可合同化）

- ZigZag 会把 **当前未确认极值** 当作序列末 pivot。  
- `AnalysisMode.PROGRESSIVE` 在该 pivot 上贴浪标 → **确认 bar 到来前标签可翻**。  
- RETROSPECTIVE 可接受；PROGRESSIVE 用于交易时必须有确认契约。

**使用边界（规定性）**：

1. **研究/回测标签图**：允许 PROGRESSIVE，报告须标注 `repaint=progressive_last_pivot`。  
2. **可交易信号**：仅允许基于 **已确认 pivot**（排除末位 in-progress），或 N-bar 确认后再 `emit_signal`。  
3. YAML 建议：`require_confirmed_pivots: true`（W18 实现时默认 true）。

### R2 — `wave_channel` 全序列 band 回填

- `wave_channel.py` 用当前 W1/W3 斜率对 **整段 df** 写 upper/lower → 历史 bar 被“事后上色”。  
- 下游若只读 `w5_target` 可接受；若把 band Series 当特征进 FeatureStore → **lookahead 陷阱**。

**使用边界**：`wave_channel` 全 band = research visualization only；特征只许标量目标/当前距离。

### R3 — Pivot 价格用 close 替代（保真，非 lookahead）

- `ZigZagIndicator.compute()` 返回 marker 1/-1/0，**丢弃真实高低点**。  
- `LiuYudongWaveStrategy._extract_pivots` 用 `df["close"]` 回填价 → 振幅/Fib/铁律幅度全偏。

**使用边界**：任何晋级相关波浪指标必须以 `compute_pivot_sequence` 的真实 high/low 为准。

### R4 — CORR-019 增量窗（已做对）

- `generate_signals` 用 `df.iloc[:end_idx]` 且只在新切片打标 → **因果设计正确**。  
- 保持；禁止改回整表一次 `elliott_wave(df)` 当权威。

### R5 — `on_bar` 空实现

- `LiuYudongWaveStrategy.on_bar` 为 pass/stub；事件路径若只调 `on_bar` 则 **零信号**。  
- paper/live 必须有桥接（累计 bar 再 `generate_signals` 末 bar，或完整 on_bar 实现）。

**使用边界**：未桥接前，波浪策略 **不得** 声称 paper_replay 晋级数字。

---

## 3. 其他缺陷（非 repaint 但影响可信度）

| 项 | 说明 | 候选 |
|----|------|------|
| low-consensus 静默单阈值回退 | `zigzag` 无共识时降级，无对外 confidence | W18-P0c |
| RSI 背离比 W1 origin | `_check_rsi_divergence` 参考点可疑 | W18-P1d |
| `WaveInvalidationChecker` 未接线 | 单测在、策略路径未见调用 | W18-P1c |
| Engine 不跑 6 wave 因子 | 需 `wave_count` 注入；`compute_all` 只跑经典 21 | 文档 + 可选接线 |
| Synthetic-only backtest | `elliott_wave_backtest` 合成波；非真实 WFO | W18-P2c |
| 文档名 `Wave-C-*` | 指 shared_RP 基线波次，**非** Elliott | 勿混淆 |

---

## 4. 波浪在 QuantFlow 的正确定位

对齐既有决策（纯规则引擎、六层内、可回测）：

| 用途 | 允许 | 禁止 |
|------|------|------|
| 结构过滤 / 失效位 / 止损参考 | ✅ | 单独当 GO 主 alpha 无合同 |
| PROGRESSIVE 实时浪标展示 | ✅ 标注 repaint | 未确认即下单 |
| 与 funding/趋势合同组合 | ✅ 新合同 B4+ | 静默塞进 B0–B3 |
| ML 混合数浪 | ❌（当前边界） | — |

**一句话**：波浪是 **可验证的规则状态机与风控几何**，不是“千人千浪”的主观 pen；也不是免验证的圣杯。

---

## 5. W18 波浪保真包（建议切片）

1. Pivot 真价路径（API 或策略改调 `compute_pivot_sequence`）。  
2. `require_confirmed_pivots` + 信号元数据 `pivot_confidence` / `consensus_n`。  
3. low-consensus：`skip` 或 `degraded=true` 强制可见。  
4. 实现/桥接 `on_bar`；接线 invalidation。  
5. 修 divergence 参考点 + 单测。  
6. 真实数据小窗 WFO 烟测文档。  

默认全部 **不改 B0**；新策略 YAML / flag。

---

## 6. 验收口径（未来实现时）

- 末 pivot 翻转场景：确认模式下 **不得** 在翻转窗内产生 entry。  
- 同 pivot 序列：真 high/low vs close 替代，Fib 水平差异有单测断言。  
- paper 路径：至少 1 条集成测证明 `on_bar` 可发单（mock bar 流）。  
- 无新增默认开启的 live 行为。  

---

*Research only. No code changed in W17.*
