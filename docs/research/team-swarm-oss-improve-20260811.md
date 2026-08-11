# Best Solution — Team Swarm vs OSS (QuantFlow 需提升点)

**Session**: `20260811-team-swarm-oss-improve`  
**Run**: `20260811-001-team-swarm`  
**Converged**: max_iterations=3  
**Best ant**: ANT-3-3 (verified_score ≈ 0.445)  
**Reference**: `Desktop/oss-quant-benchmark` + `docs/research/architecture-diagnosis-vs-oss.md`

---

## Elite path (ACO best)

```text
N_feature_store_pit
  → N_qlib_rdagent_bypass
  → N_iaf_library_not_bind
  → N_anti_overfit_gate_stack
  → N_promotion_discipline
```

**含义（研究主脊）**：PIT 特征一致 → Qlib/RD-Agent 旁路挖因子 → IAF 只作库不绑 entry → CPCV/DSR/WFO/诚实 n_trials → 仅 paper_replay 指纹晋级。

## Complementary elite path (产品/执行脊)

```text
N_research_dx_jesse_style
  → N_paper_live_parity
  → N_promotion_discipline
  → N_anti_overfit_gate_stack
  → N_path_b_oos_go_discuss
```

**含义**：Jesse 式策略 DX → paper↔live 账本一致 → 晋级纪律 → 防过拟合门 → Path B 多窗 OOS 仅 GO_DISCUSS。

## Execution / data spine (runner-up)

```text
N_orderbook_paper_sim
  → N_cost_tca_fidelity
  → N_paper_live_parity
  → N_meta_data_funding_oi
  → N_promotion_discipline
```

---

## 对抗共识：当前系统「需要提高」的地方（按优先级）

| 优先级 | 提升点 | OSS 参照 | QuantFlow 现状/证据 | 动作 |
|--------|--------|----------|---------------------|------|
| **P0** | **晋级只认 paper_replay 指纹** | nautilus 一引擎两数据源；jesse 不把 hyperopt 当晋级 | 双路径报告/OS 已有；仍须防向量化海报 | 合同/CI：任何 GO 附 paper 指纹 |
| **P0** | **Path B OOS 一致性 + 成本叙事** | jesse bootstrap；freqtrade dry-run 成本 | `path_b_oos` GO_DISCUSS，frac_beat=0.5，n=49 | 扩窗/anchored；挂 fee×slip + funding_tca；**不 live promote** |
| **P0** | **成本/TCA 不可松** | nautilus Fee/Fill；hummingbot sim fills | cost_fidelity 在位 | 保持 fail-closed；可选 orderbook-lite 滑点 |
| **P1** | **funding/OI 密历史** | 各 bot 的 meta 数据平面 | B3 稀疏 → 0 成交（诊断文档） | 补 meta parquet → 新合同，不覆盖 B 冻结 |
| **P1** | **Feature Store PIT ↔ on_bar** | qlib 时间点安全 | 方向有，审计未闭环 | 一致性测试 + 泄漏门 |
| **P1** | **Qlib/RD-Agent 旁路** | qlib RD-Agent | AGENTS V3 规划；未落地旁路作业 | 离线因子 → validation only |
| **P1** | **IAF 永不默认绑 entry** | —（swarm 既有） | `iaf_prune_cpcv` PBO≈0.73 NO-GO | hard_bind_entry=false 锁死 |
| **P2** | **Jesse 式策略 DX** | jesse 薄 API | StrategyBase 偏样板 | 模板减负 / 脚手架 |
| **P2** | **Paper orderbook-lite** | hummingbot/freqtrade dry-run | paper 成本有，盘口保真弱 | 非 HFT 的 top-of-book 滑点 |
| **P2** | **OKX 多标的组合账本** | vnpy/lean 组合 | 偏单策略路径 | 组合风险预算，**非多所超市** |
| **P3** | **可观测/运维** | OctoBot/freqtrade UX | Prometheus 规划中 | 告警分级 + 会话健康 |

## 明确「不要提高成」的方向（对抗否决）

| 否决 | 原因 |
|------|------|
| 整仓迁 Nautilus/Lean/Freqtrade | 成本极高，不自动给 alpha；B0 已证明六层可 PAPER-GO |
| 多交易所超市 / HFT 做市主线 | 非个人 OKX paper-first 边界 |
| Optuna/堆指标当晋级 | 已禁；IAF 仅库 + CPCV |
| 为抬胜率松 fee/funding 门 | 违反北极星 |
| Path A+B 合成 combined_score | dual-path 硬约束 |

## 与已交付能力的关系（避免重复劳动）

| 已交付 | 本 swarm 立场 |
|--------|----------------|
| Dual-path research OS / Path B OOS / IAF prune-CPCV | **保留**；下一刀是 OOS 加厚 + 晋级指纹，不是重做 |
| primary_w30 / TPSL SL4/TP10 | 双产品配方不变 |
| causal_preflight | 继续作门前检查 |

## 建议下一波（可立项，仍选架构选项 B）

1. **W-next-1**：promotion_path CI（paper_replay fingerprint required）  
2. **W-next-2**：Path B OOS 扩窗 + cost/funding 附件；仍 GO_DISCUSS until CPCV 改善  
3. **W-next-3**：funding/OI 密数据 + Feature Store PIT 审计  
4. **W-next-4**：Qlib/RD-Agent 离线旁路（validation only）  
5. **W-next-5**：Jesse-like 策略模板 DX  

**不做**：引擎重写。

---

## ACO 元数据

- n_ants=4 × max_iterations=3  
- scoring=fallback_self（self×confidence×0.55）  
- best_score≈0.445（discounted）— 设计综合分，非实盘 alpha  
- Artifacts: `outputs/ant-*-*.json`, `swarm-report.json`, this file  
