# QuantFlow 下一波实施计划（post T021）

**Session**: `maestro-20260809-post-t021-plan-20260809-125759`  
**上游**: T001–T021 ✅ · 非 live pytest **2154/0** · HEAD `a441d78`  
**北极星**: 成本后可复现的 paper-first **研究 OS**（GO + fee×slip + funding_tca + 钉扎合同）  
**不是 KPI**: 胜率、GitHub stars、多所超市、HFT

机器可读：`.workflow/sessions/maestro-20260809-post-t021-plan-20260809-125759/runs/20260809-001-plan/outputs/`

---

## 0. 已完成（勿重复立项）

| 范围 | 状态 |
|------|------|
| T001–T009 P0–P2 | ✅ |
| T010–T021（合同钉扎 / Alpha 三合同 / 成本门控 / 日课偏差 / catalog / 宇宙 / OSS 门禁 / 韧性演练） | ✅ |
| 全量非 live pytest | ✅ 2154 passed / 0 failed |
| B0 | **PAPER-GO**（唯一晋升） |
| B1 / B2 | **KEEP B0**（负结果一等证据，不重跑幻想升级） |

---

## 1. 本波成功定义（4–8 周）

1. **B0 Path A 日课可重复跑**（preflight → day-session → 可选 paper run），摘要含偏差/SLA 书。  
2. 至少一份 **合规 `paper_evidence`**（默认 ≥7 天 / ≥20 fills）可 `attach` → promote 路径可演示（**仍可不进 live**）。  
3. **Baseline-3 合同**写完并裁决（KEEP B0 / REJECT / 罕见 UPGRADE）；**禁止**复读 B1/B2 信号族当“新合同”。  
4. 晋级叙事始终含 **fee×slip + funding_tca**；零成本-only 拒。  
5. 不改 `portfolio_optimization.enabled` 默认 false；不改 GitHub visibility。

---

## 2. 波次总览

| 波次 | 名称 | 任务 | 目标 | 建议周次 |
|------|------|------|------|----------|
| **W10** | Paper 日课常态 | T022, T023, T024 | B0 运营闭环 + evidence | W1–3 |
| **W11** | Baseline-3 工厂 | T025, T026, T027 | 新信号族合同 + 裁决 | W2–6 |
| **W12** | 宇宙与可选加固 | T028, T029 | 扩标的 SLA；可选 checkpoint/recon 配置 | W4–8 |
| **W13** | 人审可选 | T030 | gitleaks / C 决策材料刷新（不强制公开） | 并行/按需 |

```text
T022 ──► T023 ──► T024（paper evidence）
                │
T025 ──► T026 ──► T027（B3 裁决）  （可与 W10 部分并行）
                │
T014/T019 已完成 ──► T028（扩宇宙）
T021 已完成 ──► T029（可选 ops 开关文档/overlay）
T020 已完成 ──► T030（人审，不阻塞研究）
```

---

## 3. 任务明细

### P0 — Paper 日课与样本门槛（运营主线）

| ID | 标题 | 估时 | 依赖 | done_when |
|----|------|------|------|-----------|
| **T022** | B0 日课 Runbook 固化 | 0.5–1d | T017,T019 | ✅ **done** — checklist 一条命令序列 + admitted/deviation/T016 |
| **T023** | 连续 Path A 日课执行（≥7 日历日或等价会话窗） | 7d 墙钟 / 低工程 | T022 | 🔧 **in progress** — `paper_day_streak` + 当日 Path A；**7 日连续墙钟未满** |
| **T024** | 导出/attach `paper_evidence` + promote dry-run | 1d | T016,T023 | ✅ **done**（export+dry-run；真实 streak 短→reject；synthetic 演示 pass） |

### P1 — Baseline-3（研究主线）

| ID | 标题 | 估时 | 依赖 | done_when |
|----|------|------|------|-----------|
| **T025** | Baseline-3 合同起草（信号族锁定） | 1d | T011,T013 | ✅ **done** — `funding_rate` 锁定；索引已占位 |
| **T026** | B3 challenger 流水线 + 跑数 | 2–4d | T025 | `scripts/run_baseline3_challenger.py` + `data/paper_replay/baseline3/`（WFO + fee×slip；funding 字段按 T014 合同） |
| **T027** | B3 裁决 + 索引更新 | 0.5–1d | T026 | 显式 **KEEP_B0 / REJECT / UPGRADE**；更新 `baseline-contract-index.md` |

**B3 信号族候选（T025 锁定其一，默认推荐顺序）**

| 优先级 | 族 | 理由 | 风险 |
|--------|-----|------|------|
| **1（推荐）** | **`funding_rate`（+ OI 过滤）** | B2 已 defer meta 路径；T014 后 funding 合同成熟；与 classic 趋势 **正交** | 需 meta/funding 进 bar 或专用加载；数据缺口 → 合同写清 NO-GO |
| **2** | **`momentum_rotation` 多标的** | 与 B0 单策略趋势不同（横截面）；贴合 admitted 宇宙 | 实现/对齐 shared book 成本 |
| **3** | **`elliott_wave` 或 `ml_ensemble` 固定参** | 结构/模型互补 | 易过拟合；**禁止 Optuna 晋级**；AI 须走既有 NO-GO 纪律 |
| **不做** | 重跑 donchian/MR/vol-breakout | 已是 B1/B2 冻结负结果 | 浪费 |

**升级条（继承 Wave-C / B1–B2）**

- OOS mean Sharpe > 0 且 **≥ classic 对照**（同窗同成本）  
- DD 纪律不劣于对照  
- 生产报价 **0.1% fee + 0.1% slip**；GO 叙事含 **funding_tca**  
- **无 Optuna** 作为晋级依据  
- 默认：**KEEP B0** 是合法且预期结果  

### P2 — 宇宙与运维加固

| ID | 标题 | 估时 | 依赖 | done_when |
|----|------|------|------|-----------|
| **T028** | 宇宙 +1～2 候选（download→SLA→admitted） | 1–2d | T019 | `universe.yaml` 候选更新；SLA 失败不进 baseline_default；成本网格仅 admitted |
| **T029** | Paper 路径 checkpoint/recon **可选 overlay** 文档 | 0.5–1d | T021 | overlay 或 checklist：**默认仍关**；开启步骤 + `resilience_drill` 前置 |
| **T030** | OSS C 人审包刷新（gitleaks 指引 + 决策表） | 0.5d | T020 | checklist 勾选手动项说明；**agent 不改 visibility** |

---

## 4. 按周排期（提示）

| 周 | 任务 |
|----|------|
| 1 | T022 Runbook；启动 T023 日课；T025 锁 B3 族 |
| 2–3 | T023 累积样本；T026 开跑 |
| 3–4 | T024 evidence；T027 裁决 |
| 4–6 | T028 扩宇宙（可选）；T029 overlay 文档 |
| 并行 | T030 仅当考虑公开 C |

---

## 5. 验收与证据

| 类型 | 要求 |
|------|------|
| 日课 | `data/paper_sessions/day_session_*.json` + `latest.json`（含 deviation/baseline_snapshot） |
| Evidence | `paper_days` / `fills` / 时间窗；可被 `attach_paper_evidence` 消费 |
| B3 | 合同 MD + results/gate 类 JSON + 索引行 |
| 晋级 | 禁止零成本-only；win_rate 不进 done_when |
| 测试 | 新脚本/解析聚焦 pytest；全量非 live 在波次末可选重跑 |

---

## 6. 明确放弃 / 延期

- 重开 B1/B2 只为“刷成 UPGRADE”  
- Rust / HFT / 做市 / OEMS / SaaS / 多所超市  
- 以胜率或 stars 定义本波成功  
- 未过 SLA 扩币进默认 Baseline 书  
- 默认打开 `portfolio_optimization` / 强制 live  
- Agent 修改 GitHub visibility  

---

## 7. 碰撞注意

| 资源 | 任务 | 处理 |
|------|------|------|
| `paper_day_session.py` | T022–T024 | 单写者；T017 偏差字段只增不改语义 |
| `universe.yaml` / admitted | T023, T028 | 日课读 admitted；扩宇宙另 PR |
| `cost_fidelity` / funding | T026–T027 | 只消费 T014 合同，不改 fail-closed |
| `baseline-contract-index.md` | T027 | 追加 B3 行，不改写 B0–B2 冻结结论 |
| catalog `funding_rate` | T025–T026 | 可能要接线 meta→bars；缺数据则合同 NO-GO |

---

## 8. 下一步怎么开干

```text
/maestro 执行 T022 B0 日课 Runbook 固化
```

或并行：

```text
/maestro 执行 T025 Baseline-3 合同起草（锁定 funding_rate 族）
```

日课（墙钟，可人机）：

```bash
python scripts/preflight_baseline0_paper.py
python scripts/paper_day_session.py --alert-on-fail
# 可选：--start-run / --batch-gate
python scripts/universe_expand_pipeline.py --from-config --write-admitted --dry-run-only
```

---

## 9. 与「可交易 / 开源」的关系

| 诉求 | 本波响应 |
|------|----------|
| 真要 promote | **T023–T024** 凑齐 paper_evidence；live 仍非验收默认 |
| 第二可晋升系统 | **仅当 T027=UPGRADE**；否则继续 B0-only 是成功 |
| 开源最强 | **T030** 材料；公开 = 另一次人审 |
| 胜率 | **不设**任务 |

---

*生成自 maestro plan session `maestro-20260809-post-t021-plan-20260809-125759`。*
