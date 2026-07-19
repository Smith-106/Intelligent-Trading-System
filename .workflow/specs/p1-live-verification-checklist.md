# P1 风控层实盘验证 Checklist

> **作用**：P1（F3 vol-target / F4 bootstrap CVaR / F5 MC 压力）上线后，在实盘验证周期结束时逐项对照判定 GO/NO-GO。每项给「观察什么 → 怎么看 → 判定标准」三段式，阈值全部对齐代码实际值。
>
> **串行约束**：本 checklist 全部 PASS（或 Blocker 全部修复并复验）后，方可启动 P2 AI 层（F6/F11/F12）。任何一项 NO-GO 都禁止进入 P2。

---

## P1.0 阻塞项（上线前必须先修复，否则后续验证项无法触发）

### P1.0-B1 `add_return` 零调用方 —— vol-target 与 CVaR gate 历史永不填充

**观察**：`PositionSizer.add_return()` 与 `RiskEngine.add_return()` 在全项目无任何调用方（`grep '\.add_return(' quantflow/` 返回空）。

**后果**：
- F3 vol-target：`_returns_history` 永远为空 → `_realized_vol()` 永远返回 None → vol-target 永不绑定（即使 `vol_target_pct` 已开启，opt-in 也形同虚设）。
- CVaR gate（既有，非 F4 引入）：`risk_engine._check_var` 在 `len(_returns_history) < 30` 时直接返回 passed → gate 永远不阻断。
- F4 bootstrap CVaR：诊断对象是空历史 → CI 退化，无意义。

**状态：✅ 已修复（ISS-20260719-001，commit 见下）**

**修复内容**：`quantflow/strategy/engine.py` 的 `on_bar` 在 portfolio 用当根 bar.close 标记持仓后，计算 `bar_ret = (curr_equity - prev_equity) / prev_equity`（分母是上一根 bar 收盘的 equity，在标记前捕获，无未来函数），喂给 `self._risk_engine.add_return(bar_ret)` 与 `self._position_sizer.add_return(bar_ret)`。首根 bar 用 NaN 哨兵跳过。

**单测覆盖**（`tests/unit/test_engine_extra.py::TestAddReturnWiring` + `tests/unit/test_risk_engine.py::TestCvarGateWiring`）：
- 首根 bar 不喂、第二根起喂
- 有持仓时 bar_ret 反映 equity 变化、数值正确
- 历史跨 bar 累积（5 bar → 4 笔）
- 无未来函数：分母是标记前 equity
- **CVaR gate 真正触发**：≥30 笔深尾收益 → CVaR < cvar_limit → 阻断（`reason="var_breach"`）；浅尾 → 放行；<30 笔 → 安全默认放行

**符号澄清**（修正起草时的误判）：`risk_engine._check_var` 的 `cvar_95 = returns[returns<=var].mean()` 是**负收益约定**（与 `cvar_limit=-0.05` 同号），gate 比较逻辑本身正确。此前不触发的唯一原因是 `add_return` 零调用方导致 `len<30` 短路，现已消除。注意 `risk_metrics.conditional_var` 用 `-np.mean(...)` 返回**正损失幅度**，与 `_check_var` 约定相反——两者是不同函数，F4 诊断用的是前者，gate 用的是后者，勿混。

**端到端确认**（代码层，经 `TradingSession.on_bar` 事件流，`tests/unit/test_engine_extra.py::TestP1WiringEndToEnd`，commit 见下）：
- `test_cvar_gate_blocks_signal_before_execution_in_event_flow`：stub 策略每 bar 产 LONG 信号，预填深尾历史 → on_bar 触发 `_process_signal` → `risk_engine.check` 返回 not-passed → 早 return，`submit_order` 零调用（gate 在事件流真阻断下单）。
- `test_on_bar_wiring_enables_vol_target_realized_vol`：建仓 + 35 bar 振荡价 → `_position_sizer._returns_history` 填满 deque(maxlen=30) → `_realized_vol()` 返回正值（接线前永 None）。
- `test_vol_target_on_shrinks_size_vs_off_via_on_bar_history`：相同高波动历史，ON 组 `size()` 严格 < OFF 组（缩仓在事件流层面真发生，checklist P1.1-V1 离线复现）。

1415 passed（基线 1411 + 新增 3 端到端 + 接线计数），零回归。

---

## P1.1 F3 vol-target opt-in 缩仓行为验证

> **配置开启**：在 `quantflow/config/default.yaml` 的 `risk:` 段加 `vol_target_pct: 0.15`（15% 年化目标）。`vol_annualization: 365`、`vol_window: 30` 为默认值，crypto 24/7 无需改。
> **前提**：~~P1.0-B1 已修复~~ ✅ 已修复，`_returns_history` 真实累积。

### P1.1-V1 高波动区间 vol-target 是否真的缩仓

**观察**：实盘运行 ≥30 根 bar 后，取一段 realized vol 高于历史中位数的区间（例如年化 vol ≥ 60%），记录该区间内触发的订单 notional。

**怎么看**：对比同一信号在「vol-target OFF（对照组，`vol_target_pct: null`）」与「vol-target ON」下的 `PositionSizer.size()` 返回值。可用 paper 模式双跑，或对历史 bar 离线复算。

**判定标准**：
- ✅ GO：高波动区间 ON 组 notional **显著小于** OFF 组，且约等于 `total_value * 0.15 / realized_vol`（理论 vol-target notional，扣费前）。
- ❌ NO-GO：ON 组 notional == OFF 组（vol-target 未绑定）→ 检查 `_returns_history` 是否填充、`vol_window` 是否达阈。
- ❌ NO-GO：ON 组 notional 反而 > OFF 组 → 公式符号错误，立即回滚。

### P1.1-V2 低波动区间不绑定（Kelly 主导）

**观察**：取一段 realized vol 低于 5% 年化的区间。

**判定标准**：
- ✅ GO：ON 组 notional == OFF 组（vol-target notional 远高于 Kelly/单名上限，不绑定，Kelly 行为完整保留）。
- 对应单元测试 `test_opt_in_low_vol_does_not_bind` 在实盘数据上复现。

### P1.1-V3 默认 off 的 byte-for-byte 守护

**观察**：`vol_target_pct` 不设置时，全量回测结果与 P0 commit `99795b2` 的基线完全一致。

**判定标准**：
- ✅ GO：4 策略（trend_following / mean_reversion / momentum_rotation / elliott_wave）回测的 `final_capital`、`max_drawdown`、`num_trades`、`equity_curve` 逐位相等。
- 回归测试 `test_default_off_is_byte_for_byte_baseline` 持续 PASS。
- ❌ NO-GO：off 状态下任何数值漂移 → vol-target 路径污染了 off 分支，立即回滚（违反 F3 核心契约）。

---

## P1.2 F5 路径级 MC 压力 —— 路径运气红旗是否在实盘重现

> **运行**：`quantflow validate --method stress --strategy <name> --symbol BTC/USDT`（n_paths=1000, seed=0 固定）。

### P1.2-V1 trade-shuffle 顺序风险

**观察**：实盘积累 ≥20 笔已平仓交易后，跑 trade-shuffle。关注 `prob_worse_drawdown`（重排后比观测路径回撤更深的路径占比）。

**判定标准**：
- ✅ GO（健康）：`prob_worse_drawdown` ≤ 0.5，观测路径处于重排分布的中段或偏好侧——回撤对交易顺序不敏感。
- ⚠️ 黄旗：0.5 < `prob_worse_drawdown` ≤ 0.7，观测路径偏幸运，回撤有顺序依赖——可继续运行但需监控是否恶化。
- ❌ NO-GO：`prob_worse_drawdown` > 0.7，观测路径严重依赖幸运的交易排序——实盘若遭遇不利顺序（亏损集中早期）回撤将远超回测所见。应缩减仓位或暂停策略。
- **不变量守护**：trade-shuffle 的 `p5_terminal_return == p95_terminal_return == observed_terminal_return`（置换不改总收益）——若不等说明实现退化。

### P1.2-V2 returns-bootstrap 抽样分布

**观察**：同一数据跑 returns-bootstrap，关注 terminal return 的 `[P5, P95]` 带宽。

**判定标准**：
- ✅ GO：带宽合理（P5 与 P95 同号，且 P5 不跌破 `-1` 即不爆仓）——策略收益在抽样扰动下符号稳定。
- ❌ NO-GO：P5 terminal return ≤ -0.5（半数以上本金）——单条回测路径的盈利是抽样偶然，实盘极可能重现大幅亏损。
- **对比基线**：回测期 P5/P95 带宽应作为实盘基准；实盘 terminal return 若落到带宽 P5 以下，触发复盘。

### P1.2-V3 诊断非 gate 契约

**判定标准**：
- ✅ GO：MC 结果仅展示，`validation_gate` 的 GO/NO-GO 决策不引用 MC 任何字段——`grep -n "monte_carlo\|prob_worse" quantflow/strategy/validation/gate.py` 返回空。
- ❌ NO-GO：gate.py 出现对 MC 字段的引用 → 诊断被偷偷升级为 gate，违反 claude delegate 反模式裁定，立即回滚。

---

## P1.3 F4 辅助诊断 bootstrap CVaR —— CI 是否随样本收窄

> **运行**：对 `risk_engine._returns_history`（≥30 根后）调 `bootstrap_cvar(returns, confidence=0.95, n_bootstrap=1000, seed=0)`。返回 `{point, ci_low, ci_high, n, n_bootstrap}`，值遵循 `conditional_var` 的正损失幅度约定（如 0.05 = 5% 尾部期望损失）。

### P1.3-V1 CI 宽度随样本收窄

**观察**：分别在 n=30 / n=100 / n=300 / n=500（实盘累积里程碑）记录 `ci_width = ci_high - ci_low`。

**判定标准**：
- ✅ GO：`ci_width` 随 n 单调下降（n=500 的 width 显著小于 n=30）——点估计随样本收敛，gate 判定趋于可信。
- ❌ NO-GO：`ci_width` 不随 n 下降或反升——收益分布非平稳（regime shift），historical CVaR 点估计不可靠，gate 判定不可信，需缩短 vol_window 或暂停。
- 单元测试 `test_wide_ci_for_small_sample_straddles_threshold` 守护此单调性。

### P1.3-V2 CI 与 cvar_limit 的关系（gate 可信度）

**观察**：`cvar_limit` 当前为 `-0.05`（config.py:60）。符号澄清：`risk_engine._check_var` 的 CVaR 用**负收益约定**（`returns[returns<=var].mean()`，负数），与 `cvar_limit=-0.05` 同号比较，gate 逻辑正确且现已在历史填满后生效（P1.0-B1 已修复）。而 F4 `bootstrap_cvar` 包装的 `risk_metrics.conditional_var` 返回**正损失幅度**（`-np.mean(...)`）——两者约定相反，比较 CI 与阈值时统一取绝对值：gate 实际阈值是「CVaR 损失幅度 > 0.05 即阻断」。

**判定标准**：
- ✅ GO（gate 可信）：`ci_high`（最严重侧）仍 < 0.05 → 即使最坏抽样，CVaR 也没触碰阈值，gate 的 passed 判定稳健。
- ⚠️ 黄旗：`ci_low < 0.05 < ci_high` → CI 跨越阈值，gate 判定样本脆弱，应继续累积数据再下结论。
- ❌ NO-GO：`ci_low` > 0.05 → 即使最轻抽样也超阈值，gate 应判 NO-GO 但若实际 passed 说明历史未喂或 `_check_var` 回归失效（回归测试 `test_gate_blocks_when_tail_breaches_limit` 守护）。

### P1.3-V3 辅助非 gate 契约

**判定标准**：
- ✅ GO：`bootstrap_cvar` 仅在诊断/CLI 路径调用——`grep -n "bootstrap_cvar" quantflow/signal/risk_engine.py` 返回空。historical CVaR 仍是 `_check_var` 唯一数据源。
- ❌ NO-GO：risk_engine 引用 `bootstrap_cvar` 作为 gate 输入 → 诊断被升级为 gate，违反反模式裁定，立即回滚。

---

## 汇总判定

| 项 | 类型 | 判定 |
|----|------|------|
| P1.0-B1 add_return 接线 | Blocker | ✅ 已修复 + 8 单测（ISS-20260719-001） |
| P1.0-B1 端到端确认（事件流） | Blocker | ✅ 3 单测经 on_bar 链确认 gate 阻断下单 / vol-target 缩仓 / 历史填充 |
| P1.1-V1 高波动缩仓 | GO/NO-GO | ☐ |
| P1.1-V2 低波动不绑定 | GO/NO-GO | ☐ |
| P1.1-V3 off byte-for-byte | GO/NO-GO | ☐ |
| P1.2-V1 trade-shuffle 顺序风险 | GO/NO-GO | ☐ |
| P1.2-V2 returns-bootstrap 带宽 | GO/NO-GO | ☐ |
| P1.2-V3 MC 诊断非 gate | 契约 | ☐ |
| P1.3-V1 CI 随样本收窄 | GO/NO-GO | ☐ |
| P1.3-V2 CI vs cvar_limit | gate 可信度 | ☐ |
| P1.3-V3 CVaR 诊断非 gate | 契约 | ☐ |

**进 P2 条件**：P1.0-B1 已修复且复验 + 全部 GO/NO-GO 项 PASS + 两个「诊断非 gate」契约项 PASS。任一 NO-GO 或契约破裂 → 停在 P1，不得启动 P2。

**验证周期建议**：≥30 个交易 bar（满足 `vol_window` 与 CVaR 的 `len < 30` 阈）+ ≥20 笔已平仓交易（满足 trade-shuffle 统计意义）。crypto 24/7，按 1d bar 约 30 天，按 1h bar 约 30 小时——周期长度由所配 timeframe 决定。

---

## 离线/模拟实盘可执行性（2026-07-19 增补）

回答「能否用历史实盘历史模拟实盘跑 F4/F5」——三步前置工作结论：

### 1. parity 守卫（commit `4c2dbd0`）——P1-verify F3 地基

逐 bar 比对 trend_following 增量路径 `_latest_signal()` vs 向量化 `generate_signals`，5 seed × 全序列（`TestSignalParityGuard`）：
- ✅ **ENTRY 信号 0 漂移**（5/5 seed 全绿）——F3 用 paper-on_bar 跑、F5 用 BacktestEngine 跑，两路径入场信号完全一致，F3 缩仓结论可信。
- ⚠️ **EXIT 信号系统性漂移**（12..22/122 bars/seed）——ISS-20260613-006 具体落点：`_latest_signal` exit 用「无 vol_ok + 阈值 min_conditions-1」，`generate_signals` exits 用「含 vol_ok + 阈值 min_conditions」再 OR profit/trailing。设计性语义不一致，先于 P1 存在，固化为已知区间 (1..30) 不阻塞——避免扰动 P1 byte-for-byte 回归守卫。待 ISS-006 裁决 exit 统一语义后升级为严格 parity。

### 2. F5 输入源确认（commit `4f5e218`）——数据流已通

`validate --method stress` 当前完全绑死 `BacktestEngine`（`trade_returns`/`bar_returns` 都来自 `bt`）。但 `bootstrap_cvar`/`monte_carlo_stress` 是纯 list 接口——paper session 的 `_risk_engine._returns_history`（on_bar 接线填充）可直接喂入。`TestPaperReplayFeedsF4F5Diagnostics` 实证：
- ✅ F4（`bootstrap_cvar`）+ F5 returns-bootstrap（`monte_carlo_stress(bar_returns=...)`）现在即可用 paper 回放数据跑，无需改代码。
- ⚠️ F5 trade-shuffle 需补 per-trade returns 收集（paper session 尚未配对开仓/平仓成 trade），属单独增强项。

### 3. paper 历史回放脚本（commit `ce4d9b4`）——工具就绪

`scripts/replay_paper_f4f5.py`：回放本地 parquet 经 `TradingSession.on_bar`（手动注入 PaperGateway 绕过 start() 副作用），取 returns 历史喂 F4/F5。烟测试端到端通。

**信号密度约束**：trend_following `required_regime="trending"`，真实 BTC/USDT 1h parquet（2024-12..2025-06）仅 ~21/676 bar 为 trending → 回放产出的 bar returns 多为 0。非 P1 接线问题，是策略/数据特性。要积累非零 returns 需：trending 数据段 / 非 trending regime 策略 / 调参。

**副发现（更深 parity 缺口）**：on_bar 事件路径应用 regime gating（`required_regime` + `MarketRegimeDetector`），而 `generate_signals` 向量化路径**不应用** regime gating——两路径在 regime 维度本就不 parity。这比 ISS-006 的 exit 漂移更结构性：回测（generate_signals）会交易所有 bar 的信号，实盘（on_bar）只在对应 regime 交易。属既有设计，登记为后续 parity 守卫待补项（regime 维度），不在 P1-verify 范围强修。
