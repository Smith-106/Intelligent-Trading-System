# W17 — 防未来函数强化 + 指标补强清单

**Date**: 2026-08-10  
**Source audit**: factor-audit + wave-audit（通道/增量）+ smart-search look-ahead  
**Related**: [w17-small-team-edge.md](./w17-small-team-edge.md) · T003 Feature Store PIT  

---

## 1. 防未来：当前水位

### 已做得对

| 机制 | 位置 | 说明 |
|------|------|------|
| 查询截止 | `DataStore.query(..., end=timestamp)` | `timestamp <= end` |
| Feature 计算 | `FeatureStore.compute_features` | raw 带 end；funding/OI 同截止 + as-of merge |
| 经典指标 | rolling / `shift(1)` 习惯 | pure pandas/numpy，无 TA-Lib 运行时依赖 |
| 波浪增量信号 | CORR-019 `iloc[:end_idx]` | 避免整表未来 pivot 污染 entry |
| Meta 新鲜度 | funding/OI fresh gates | fail-closed 读侧 |

### 缺口与强化清单

| ID | 风险 | 现状 | 建议（W18+） |
|----|------|------|--------------|
| AF-1 | 调用方传错 `timestamp` | PIT 全靠 caller | 集成测：乱序/未来 ts 应拒绝或裁剪；文档强制 |
| AF-2 | `save_features` 同 timestamp 后写覆盖 | `drop_duplicates(keep="last")` | keep-first 或 content hash 冲突告警 |
| AF-3 | `load_features` 无 as-of 语义 | 区间裸读 | 研究 API 增加 `asof=` 或文档禁止当 PIT 源 |
| AF-4 | IndicatorComputer 不校验因果 | Protocol 信任实现 | 对新增因子强制单测 `no_lookahead` 模板 |
| AF-5 | wave_channel 全带回填 | 见波浪分册 | 禁止进 FeatureStore 默认集 |
| AF-6 | ZigZag 末 pivot repaint | 见波浪分册 | 交易路径确认 pivot |
| AF-7 | 整表 `elliott_wave(df)` toy | 模板轨 | 弃用为权威路径 |
| AF-8 | 缺专用 PIT 泄漏回归 | 审计未见强测 | 恢复/加强 T003 精神：强制门测 |

外部共识：look-ahead 是“纸面圣杯、实盘哑弹”的主因之一（smart-search / Medium 2024-09）。对本仓：**门禁与测试比再写一个因子更值钱**。

---

## 2. 因子表面：真实结构（纠正口径）

### 双轨（不要再混称）

| 表面 | 数量 | 机制 |
|------|------|------|
| `IndicatorEngine.FACTOR_NAMES` | **27 名** | 21 经典函数 + 6 wave **名** |
| `FactorRegistry` | **6** | 仅 Elliott `FactorBase` 类 |
| `batch_calculate` / `compute_all` | **21 经典** | **不调用** 6 wave（缺 `wave_count` 注入） |
| 休眠已实现函数 | **5** | 未进 `FACTOR_NAMES` / 未接线 |

> 文档/`.workflow` 若写 “27 registered factors” → **错误**。正确说法：  
> **Engine 暴露名 27；可批量计算经典 21；Registry 注册 wave 6；另有休眠实现 5。**

### 21 经典（已接线）

- Trend 7: sma_20, sma_50, ema_12, ema_26, macd, macd_signal, macd_histogram  
- Momentum 4: rsi_14, stoch_k, stoch_d, williams_r_14  
- Volatility 5: atr_14, bb_*, adx_14  
- Volume 5: obv, vwap, mfi_14, volume_sma_20, volume_ratio  

### 休眠（已实现，**优先接线**）

| 函数 | 文件 | 产出列 |
|------|------|--------|
| `supertrend` | `trend.py` | supertrend, supertrend_direction |
| `dema` | `trend.py` | dema |
| `stochastic_rsi` | `momentum.py` | stoch_rsi 等 |
| `keltner_channel` | `volatility.py` | kc_upper/middle/lower |
| `donchian_channel` | `volatility.py` | dc_upper/middle/lower |

接线清单（三处同步，缺一即隐身）：

1. `FACTOR_NAMES` 追加名  
2. `batch_calculate` 分支  
3. `compute_all` 的 `if name in requested` 分支  

### 6 wave 名（Registry 有，Engine 批量无）

`zigzag_pivots, wave_count, fibonacci_levels, critical_levels, wave_channel, divergence`  
→ 仅适合 **带 wave_count 的专用管道**，不要假装 `compute_all()` 已算。

---

## 3. 真正缺失的主流族（按小团队 ROI）

| 优先级 | 因子族 | 现状 | 建议 |
|--------|--------|------|------|
| P1 | 休眠五件套 | 已有代码 | **只接线 + 测**，零算法发明 |
| P2 | VWAP 变体 | 仅全局 vwap | session / rolling VWAP（bar 级可做） |
| P2 | 量能扩展 | 仅 obv | OBV-MA/slope；CMF（若有合适 volume 定义） |
| P3 | CVD 代理 | 无 | 需 trade/agg 流；无数据不做 |
| P3 | Ichimoku / CCI / ROC / SAR | 无 | 合同驱动再加 |
| — | TA-Lib 运行时 | optional extra 未 import | **保持 pure pandas**；不必绑死 |

**原则**：先把已写未暴露的变成可用，再谈“更多指标”。

---

## 4. 安全添加因子（操作契约）

```text
1. 实现因果函数（仅 past/rolling；信号用 shift(1) 若需“上 bar 确认”）
2. 单元测：已知序列 + 截断尾部后前缀不变（no_lookahead）
3. 三处接线：FACTOR_NAMES + batch_calculate + compute_all
4. FeatureStore 子集名更新（若 catalog 有白名单）
5. 默认不进任何冻结基线合同；新研究用新 feature set id
```

Registry 路径（`FactorBase`）：

- `register` **不会**自动进 `compute_all`  
- 波类因子继续专用管道；或显式 adapter  

层约束：`data/` 不得 import `indicators/`（已有单测）。

---

## 5. 指标补强 vs 防未来：打包建议

| 波次切片 | 内容 |
|----------|------|
| **AF pack** | AF-2 写保护 + AF-8 PIT 回归 + AF-5/6 文档与 wave 确认 |
| **Factor expose pack** | 休眠五件套接线 + 口径文档修正 + list_available 单测 |
| **Factor new pack** | session VWAP + OBV slope（可选） |

不与 B0 数字绑定；`portfolio_optimization` 仍默认 false。

---

## 6. 验收口径（未来实现）

- `list_available()` 含休眠名；`compute_all(names=...)` 列齐全。  
- 截断 OHLCV 后缀后，前缀特征值 **逐位相等**（核心因子抽样）。  
- `save_features` 同 ts 冲突行为有文档 + 测。  
- 文档中不再出现“27 registered factors”歧义句。  

---

*Research only. No code changed in W17.*
