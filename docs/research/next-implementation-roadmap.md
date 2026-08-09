# QuantFlow 下一波实施计划表（post T001–T009）

**Session**: `maestro-20260809-next-impl-plan-20260809-092144`  
**上游**: strongest-gaps P0–P2 已完成 · 薄弱点审计 2026-08-09 · 全量 pytest 2102/5  
**北极星**: 成本后可复现的 paper-first **研究 OS**（GO + fee×slip + 钉扎合同）  
**不是 KPI**: 胜率、GitHub stars、多所超市、HFT

机器可读：`.workflow/sessions/maestro-20260809-next-impl-plan-20260809-092144/runs/20260809-001-plan/outputs/`

---

## 0. 已完成（勿重复立项）

| ID | 标题 | 状态 |
|----|------|------|
| T001–T004 | 成本门 / Baseline 双报 / PIT+质量 / day-session | ✅ P0 |
| T005–T007 | 脚手架+Path A/B / AI NO-GO / OKX 状态机 | ✅ P1 |
| T008–T009 | 宇宙 SLA 流水线 / docs-demo 公开包 | ✅ P2 |
| **T010** | 全量 pytest 收口：金标 pin + validate mock | ✅ **done**（2108 passed；`9ba1145`） |
| **T011** | 研究合同时间窗钉扎（data pin / fingerprint） | ✅ **done**（`contract_pin` + run_meta） |
| **T012** | Baseline-1 第二信号族 | ✅ **done** — **KEEP B0**（non-MA 未过 Wave-C 升级） |
| **T013** | 第三互补 Baseline 合同 | ✅ **done** — **KEEP B0**（MR/vol 未过升级；三合同索引） |
| **T014** | Funding / TCA 进成本合同 | ✅ **done**（`funding_tca` fail-closed on register） |
| **T015** | 批处理门控产线 | ✅ **done**（`batch_gate_pipeline` + day-session hook） |
| **T016** | Paper 最短样本/天数硬门槛 | ✅ **done**（promote fail-closed + YAML） |
| **T017** | 日课偏差告警 vs Baseline | ✅ **done**（day-session deviation + alert hook） |

---

## 1. 成功定义（8–12 周密集 / 6 个月完整）

1. 非 live 全量 pytest **绿**（或仅文档化 xfail）  
2. **≥3** 个 Baseline 合同可复跑同结论  
3. **批处理门控** + **最短 paper 门槛** 上线  
4. **funding/TCA** 进入成本叙事  
5. 开源方案 **C 仅门禁就绪**（是否公开仍人审）

---

## 2. 波次总览

| 波次 | 名称 | 任务 | 目标 | 建议周次 |
|------|------|------|------|----------|
| **W5** | 工程卫生与合同钉扎 | T010, T011 | 消灭假红/假绿，可复现地基 | W1 |
| **W6** | Alpha 工厂 | T012, T013 | ≥3 Baseline 合同产能 | W2–6 |
| **W7** | 成本深度与门控产线 | T014, T015, T016 | 工厂化验证 | W4–8 |
| **W8** | 日课与资产卫生 | T017, T018, T019 | 可运营 | W6–10 |
| **W9** | 开源门禁与韧性 | T020, T021 | 可选 C / 恢复演练 | W10–12 |

```text
T010 ──► T011 ──┬──► T012 ──► T013
                │
                ├──► T014 ──► T019
                │
                └──► T015 ──► T016
                         └──► T017

T010 ──► T020
T018（可并行）
T021（可并行）
```

---

## 3. 任务明细

### P0（必须先做）

| ID | 标题 | 估时 | 依赖 | done_when |
|----|------|------|------|-----------|
| **T010** | 全量 pytest 失败收口：金标 pin + validate mock | 0.5–1d | — | 非 live 全绿或 documented xfail；guard pin `end_ms`；validate 不跑全历史 |
| **T011** | 研究合同时间窗钉扎（data pin / fingerprint） | 1d | T010 | run_meta 含 start/end + data_fingerprint |
| **T012** | Baseline-1：第二信号族（非 classic 单路径） | 3–5d | T011 | WFO+fee×slip 合同 + KEEP/REJECT/UPGRADE 裁决书 |

### P1（主价值）

| ID | 标题 | 估时 | 依赖 | done_when |
|----|------|------|------|-----------|
| **T013** | 第三 Baseline 合同（互补） | 3–5d | T012 | 累计 ≥3 合同 + 互补说明 |
| **T014** | Funding / TCA 进成本合同 | 2–3d | T011 | GO 叙事必引 funding 字段 |
| **T015** | 批处理门控产线 | 2–3d | T010, T011 | 一键多策略 gate+cost 汇总 |
| **T016** | Paper 最短样本/天数硬门槛 | 1d | T015 | 不满足 → rejected |
| **T017** | 日课偏差告警 vs Baseline | 2d | T015 | day-session 摘要含偏差/告警钩子 |

### P2（增强）

| ID | 标题 | 估时 | 依赖 | done_when |
|----|------|------|------|-----------|
| **T018** | catalog 注册补齐 / disabled 显式化 | 1d | — | 无 `No factory registered` 刷屏 |
| **T019** | 宇宙扩展常态产线（清单 YAML） | 2d | T014 | SLA→入池；未过 SLA 不进默认 baseline |
| **T020** | 开源 C 门禁清单（不强制公开） | 1–2d | T010 | CONTRIBUTING + secret-scan + CI 建议 |
| **T021** | 崩溃恢复/对账告警闭环 | 1–2d | — | 损坏/漂移测试绿；TODO→修或 ISS |

---

## 4. 按周排期（提示）

| 周 | 任务 |
|----|------|
| 1 | T010, T011 |
| 2–4 | T012 |
| 4–6 | T013, T014（T014 可与 T013 部分并行） |
| 6–8 | T015, T016, T017 |
| 8–10 | T018, T019 |
| 10–12 | T020, T021 |

---

## 5. 验收与证据约定

| 类型 | 要求 |
|------|------|
| 代码任务 | 聚焦 pytest + 变更文件列表 |
| 研究合同 | `docs/research/Candidate-Baseline-N.md` + results + gate JSON |
| 脚本 | dry-run 命令 + 样例输出路径 |
| 晋级 | 禁止零成本-only GO；win_rate 不进 done_when |

---

## 6. 明确放弃 / 延期

- Rust 内核 · HFT · 做市 · 机构 OEMS · SaaS 跟单  
- 以 **胜率海报** 或 **stars** 定义成功  
- 未过数据 SLA 的扩币军备  
- 多所连接器超市  

---

## 7. 碰撞注意

| 文件 | 任务 | 处理 |
|------|------|------|
| `cost_fidelity.py` | T014, T015 | T014 先扩字段，T015 只消费 |
| `paper_day_session.py` | T017 | 单写者 |

---

## 8. 下一步怎么开干

```bash
# 建议：先 W5
# 1) 修金标 + validate mock（T010）
# 2) 钉 pin 窗（T011）
# 然后开 Baseline-1 研究合同（T012）
```

或：

```text
/maestro 执行 T010 全量 pytest 失败收口
```

---

## 9. 与「开源最强 / 胜率」的关系（计划约束）

| 诉求 | 计划如何响应 |
|------|----------------|
| 开源最强 | T020 只做 **门禁**；公开 = 另一次人审（方案 C），不阻塞 Alpha 工厂 |
| 交易胜率 | **不设** win_rate 任务；T012–T014 优化 **成本后稳健期望** |

---

*生成自 maestro plan run `20260809-001-plan`。*
