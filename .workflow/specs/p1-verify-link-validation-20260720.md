# P1-verify 链路验证报告

**日期**：2026-07-20
**状态**：链路验证 PASS / 实盘诊断待数据策略问题解决（进行中）
**执行人**：claude（goal 第 2 步）

## 前置条件（全部就绪）

| 前置 | 状态 | 证据 |
|------|------|------|
| parity 地基（ISS-006 exit 修复） | ✅ | commit `0dbee17`，守卫 `TestSignalParityGuard` 5/5 seed ENTRY 0 漂移 |
| regime 缺口裁决（ISS-20260720-001） | ✅ design-property | commit `98d36f0`，两层设计文档标注 + `TestRegimeParityGap` 守卫 |
| VaR 肥尾（ISS-20260718-004） | ✅ | commit `ac0377e`，gate 已 historical ES + parametric fat-tail 警示 |
| F4/F5 数据流接通 | ✅ | commit `4f5e218`，`TestPaperReplayFeedsF4F5Diagnostics` |
| paper 回放脚本 | ✅ | commit `ce4d9b4` + 本次增强 `--strategy` 参数 |

## 链路验证（PASS）

用 `scripts/replay_paper_f4f5.py` 回放真实 BTC/USDT 1h（676 bar）经 `TradingSession.on_bar`（实盘忠实路径，含 regime gate）：

- ✅ 676 bar 回放完成，无异常
- ✅ returns 累积 500（首 bar 跳过，无 look-ahead，ISS-20260719-001 接线生效）
- ✅ F4 `bootstrap_cvar` 诊断产出（point/CI/ci_width/n/n_bootstrap 格式正确）
- ✅ F5 `monte_carlo_stress` returns-bootstrap 诊断产出（P5/P95/prob_worse_dd 格式正确）
- ✅ on_bar → `_returns_history` → F4/F5 链路端到端通

**结论**：P1-verify 的链路可执行性已验证——parity 地基在真实数据流上工作，F4/F5 诊断接口正确。

## 实盘诊断受阻（待解决）

F4/F5 诊断值全 0（point=0, CI=[0,0], P5/P95=[0,0]）——returns 全 0 因策略未开仓。两个阻塞：

### 阻塞 1：trend_following 被 regime gate（ISS-20260720-001，已裁决 design-property）
- trend_following `required_regime="trending"`，真实 BTC/USDT 1h 仅 21/676 bar trending
- 84 个 generate_signals entries 全落在非 trending bar → on_bar 全 gate → 零交易
- 已裁决为两层设计特性（regime 宏观门控 vs entry 微观信号），非 bug
- **缓解**：P1-verify 实盘诊断需用 trending 数据段 或 非 trending regime 策略

### 阻塞 2：mean_reversion on_bar 不发信号（ISS-20260720-002，新发现，high）
- 为绕开阻塞 1 选 mean_reversion（required_regime="mean_reversion"，非 trending 市交易）
- 实测 on_bar 发 **0 信号**，但 generate_signals 产 11 entries / 59 exits
- 增量 on_bar 与向量化严重不 parity（比 ISS-006 exit 漂移更彻底）
- **阻塞 P1-verify**：mean_reversion 本应作为非 trending 数据源，但其 on_bar 不发信号导致 returns 全 0
- **待修**：对齐 mean_reversion on_bar entry 条件与 generate_signals，补 parity 守卫

## checklist 项状态

| 项 | 状态 | 说明 |
|----|------|------|
| P1.0-B1 add_return 接线 | ✅ PASS | ISS-20260719-001 修复 + 8 单测 |
| P1.1-V1 高波动缩仓 | ⏳ 待数据 | 需非零 returns，受阻塞 1+2 |
| P1.1-V2 低波动不绑定 | ⏳ 待数据 | 同上 |
| P1.1-V3 off byte-for-byte | ✅ PASS | `test_default_off_is_byte_for_byte_baseline` |
| P1.2-V1 trade-shuffle 顺序风险 | ⏳ 待数据 | 需 ≥20 平仓交易（paper session 尚未收集 per-trade returns） |
| P1.2-V2 returns-bootstrap 带宽 | ⏳ 待数据 | 链路通，诊断值待非零 returns |
| P1.2-V3 MC 诊断非 gate | ✅ PASS | gate.py 无 monte_carlo 引用 |
| P1.3-V1 CI 随样本收窄 | ⏳ 待数据 | 链路通，需非零 returns 多 n 里程碑 |
| P1.3-V2 CI vs cvar_limit | ⏳ 待数据 | 同上 |
| P1.3-V3 CVaR 诊断非 gate | ✅ PASS | risk_engine 无 bootstrap_cvar 引用 |

## 进 P2 条件评估

- ✅ P1.0-B1 已修复复验
- ✅ 两个「诊断非 gate」契约项 PASS（P1.2-V3, P1.3-V3）
- ✅ off byte-for-byte PASS（P1.1-V3）
- ⏳ 6 项 GO/NO-GO 待实盘数据（受阻塞 1 design-property + 阻塞 2 ISS-20260720-002）

**结论**：P1-verify 链路 PASS，但 6 项 GO/NO-GO 实盘诊断待 ISS-20260720-002 修复（mean_reversion on_bar parity）+ 合适数据段/策略组合。**未满足进 P2 条件，停在 P1**。

## 下一步

1. **修 ISS-20260720-002**（mean_reversion on_bar parity）——P1-verify 实盘诊断的真正解锁项
2. 修复后用 mean_reversion 在真实 BTC/USDT 1h 跑回放，产出非零 F4/F5 诊断
3. 补 F5 trade-shuffle 的 per-trade returns 收集（paper session 配对开仓/平仓）
4. 积累 ≥30 bar + ≥20 平仓交易后，逐项判定 6 个 GO/NO-GO
