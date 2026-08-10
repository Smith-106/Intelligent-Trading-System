# 残留收口状态：运营 streak · 人审 · promote 证据

**Date**: 2026-08-10  
**Session**: residual-close（post wave-close）  
**HEAD**: see `main`  
**Honesty**: 不伪造 7 日；不改 visibility；不把 synthetic promote 当真实 ops  

---

## 总览

| 残留类 | 本轮结果 | 是否仍开放 |
|--------|----------|------------|
| **A. 日课 streak** | 刷新至 **3/7** 连续 UTC 日 | 🔧 是（墙钟） |
| **B. 可选人审** | `oss_c_gate` 绿；**git 历史 gitleaks = 0**；工作区 2 命中（本地未跟踪路径） | 🔧 人审项 |
| **C. 真实 promote 证据** | dry-run **rejected**（days=3 &lt; 7；fills=5 &lt; 20） | 🔧 依赖 A |

---

## A. Path A streak（运营累计）

| 字段 | 值 |
|------|-----|
| credited | `2026-08-08`, `2026-08-09`, **`2026-08-10`** |
| consecutive | **3** |
| target_met (min_days=7) | **false** |
| 今日 Path A | preflight OK · deviation ok |

```bash
python scripts/paper_day_streak.py ingest --run-day-session
python scripts/paper_day_streak.py status --min-days 7
```

**剩余**: 至少再 **4** 个连续 UTC 日 credit。禁止补写历史日期。

详见 [t023-streak-status.md](./t023-streak-status.md)。

---

## B. 可选人审（材料 + 扫描）

### 自动门禁

```text
python scripts/oss_c_gate.py --quick
→ ready_for_human_c_review=True · blockers=none · secret_scan hits=0
```

### gitleaks

| 范围 | 结果 |
|------|------|
| **Git 历史**（`gitleaks detect --source .`） | **no leaks found**（254 commits） |
| **工作区 --no-git** | **2 findings**（见下；**不在 git 历史**） |

工作区命中（**已脱敏摘要**；完整 report 仅本地，勿提交）：

| # | Rule | File（本地） | 处置建议 |
|---|------|--------------|----------|
| 1 | generic-api-key | `.workflow/recovery/compaction-checkpoints/…` | 确认 recovery 已 gitignore；勿 commit |
| 2 | generic-api-key | `data/live_evidence/live_connection_*.json` | 确认 `data/` 已 gitignore；含连接证据则轮换/删除本地敏感字段 |

**人仍需勾选**（[oss-c-human-review-pack.md](./oss-c-human-review-pack.md)）：

- [ ] 决策表填写（Stay B / Start C / Defer）
- [ ] 工作区 2 命中已人工复核（非历史泄漏）
- [ ] **Visibility 仅人类操作**（agent 禁止）

---

## C. 真实 paper_evidence / promote

| 路径 | 结果 |
|------|------|
| 管道 | T024 ✅（export + dry-run 可用） |
| **真实** streak 导出 + promote | **rejected** — `paper_days=3 < 7`；`fills=5 < 20`（T016 fail-closed） |
| synthetic-full | 仅演示 pass；**不算** ops 完成 |

```bash
# 满 7 日且有真实成交后：
python scripts/paper_evidence_export.py dry-run --fills <真实成交数>
```

---

## 完成定义（本文件语义）

| 声明 | 含义 |
|------|------|
| **工程/管道完成** | streak 工具、evidence 工具、oss 材料、门禁脚本均已交付 |
| **运营未满** | consecutive &lt; 7 或真实 fills 不足 → promote 必须 reject |
| **人审未决** | C 方案 visibility / 决策表仍属人类 |
| **本轮可宣称** | 三类残留均已 **诚实扫尾与状态固化**；无静默标绿 |

---

## 每日最小动作

```bash
python scripts/paper_day_streak.py ingest --run-day-session
python scripts/paper_day_streak.py status --min-days 7
```

满 7 日后补跑真实 evidence dry-run；人审按 pack 勾选。

*Residual close — honest progress, no fake completion.*
