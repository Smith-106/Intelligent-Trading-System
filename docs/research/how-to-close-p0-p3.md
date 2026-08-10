# 怎么完成 P0–P3（操作手册）

**As of**: 2026-08-10  
**前提**: 工程 wave 已关；本手册只解决 **运营 / 人审 / 可选研究**，不开 W28。  
**诚实规则**: 不伪造 UTC 日；不用 `--synthetic-full` 冒充真实 promote；agent 不改 GitHub visibility。  
**Doable-close 快照**: [doable-close-20260810.md](./doable-close-20260810.md)（同日可做项已执行；T023 仍 3/7；3 session lifecycle-drift DEFER）。

---

## 总览

| 优先级 | 目标 | 谁做 | 能否今天做完 |
|--------|------|------|----------------|
| **P0** | T023 → 7/7 再 T024 真实 evidence | **你 + 日历** | **否**（约需再 4 个 UTC 日） |
| **P1** | seal 阻塞 session + knowledge 人审 | 人（可选 agent 辅助） | 部分可以 |
| **P2** | Scheme C 决策 + wiki 误报 | **仅人** / upstream | 决策可以；wiki100 未必 |
| **P3** | 新研究合同 B6+ | 有假设才做 | 无假设则 **跳过** |

---

# 1. P0 — 唯一硬缺口

## 1.1 现状

```text
consecutive = 3 / 7
credited    = 2026-08-08, 2026-08-09, 2026-08-10
target_met  = false
```

**还缺**: 从 **下一个 UTC 日** 起，再连续 credit **4 天**（例如 08-11…08-14，以实际 UTC 日历为准）。  
**禁止**: 回填 08-04…08-07，或预写未来日。

## 1.2 每天做什么（Path A / T023）

在仓库根目录，**每个 UTC 日最多 credit 一次**：

### 方式 A（推荐，Windows）

```powershell
cd C:\Users\niko\Desktop\智能交易系统
$env:PYTHONUTF8 = "1"
pwsh -File scripts/path_a_daily.ps1
```

`path_a_daily.ps1` 内部会：

1. `paper_day_streak.py ingest --run-day-session`（跑日课摘要 + 记入 ledger）  
2. `paper_day_streak.py status --min-days 7`

### 方式 B（等价分步）

```bash
export PYTHONUTF8=1
cd /path/to/智能交易系统

# 1) Path A 日课：preflight + summary（默认不挂长跑 paper）
python scripts/paper_day_session.py

# 可选：操作员在场要挂 paper 进程时
# python scripts/paper_day_session.py --start-run

# 2) 记入 streak（每 UTC 日 ≤1 次）
python scripts/paper_day_streak.py ingest

# 3) 看进度
python scripts/paper_day_streak.py status --min-days 7
python scripts/paper_day_streak.py report --min-days 7
```

### 通过标准（T023 完成）

```text
consecutive >= 7
target_met  == true   # 或 target_met_consecutive == true
```

查看：

```bash
python scripts/paper_day_streak.py status --min-days 7
# 读 data/paper_sessions/streak_report.json
```

### 日课注意

| 情况 | 处理 |
|------|------|
| preflight WARN bar age | 可选刷新：`python -c` 调 CLI download，或文档中的 quantflow download |
| preflight FAIL | **先修数据/配置**，再 ingest；失败日不要硬 credit |
| 同一 UTC 日跑多次 | ledger 仍只记 **1** 天 |
| 想“补”过去的天 | **禁止** |

### 日历示意（从 3/7 出发）

| UTC 日 | 动作 | 期望 consecutive |
|--------|------|------------------|
| 已有 08-08…08-10 | 已 credit | 3 |
| 下一 UTC 日 | Path A + ingest | 4 |
| +1 | 同上 | 5 |
| +1 | 同上 | 6 |
| +1 | 同上 | **7 → target_met** |

（若中间断一天，consecutive 会断档，需重新连满 7。）

## 1.3 T023 满后：T024 真实 evidence

**仅当** `target_met` 为 true（或你确认 consecutive≥7）再执行。

### 步骤

```bash
export PYTHONUTF8=1

# 1) 从真实 streak 导出 paper_evidence（不要用 --synthetic-full）
python scripts/paper_evidence_export.py export
# 若脚本要求成交数，用真实 fills，例如：
# python scripts/paper_evidence_export.py export --fills <真实成交数>

# 2) dry-run：独立 registry 上 register → attach → promote（不碰真 live）
python scripts/paper_evidence_export.py dry-run
# 或带真实 fills：
# python scripts/paper_evidence_export.py dry-run --fills <真实成交数>

# 3) 看结果
# data/paper_sessions/paper_evidence_latest.json
# data/paper_sessions/promote_dry_run_latest.json
```

### T016 门槛（fail-closed）

| 字段 | 默认门槛 | 不足时 |
|------|----------|--------|
| paper_days | ≥ **7** | promote **rejected**（正确） |
| fills | ≥ **20**（配置为准） | 同上 |

### 完成定义（T024 ops）

- [ ] evidence 来自 **真实** streak / session，不是 `--synthetic-full`  
- [ ] `paper_days`、`fills` 过 T016  
- [ ] `dry-run` 的 promote 不再因样本不足 reject  
- [ ] **真 live promote 仍默认不做**；仅人类明确授权后再做  

### 禁止

```bash
# 仅演示“能 pass”的路径 —— 不算 ops 完成
python scripts/paper_evidence_export.py dry-run --synthetic-full
```

### 若 dry-run 仍 reject

1. 读 `promote_dry_run_latest.json` 的 reason  
2. 常见：days&lt;7、fills&lt;20、缺 fingerprint/路径  
3. **不要降门槛**；继续 Path A 或真实 paper 成交积累  

---

# 2. P1 — 可选卫生

## 2.1 Seal 仍阻塞的 session

当前典型（历史）：

| session_id | 阻塞原因 |
|------------|----------|
| `a-b-mr-88-sma200-20260807-101222` | unsealed Run `analyze` |
| `a-b-mr-88-sma200-20260807-101321` | 同上 |
| `maestro-arch-iss003-004-005-011-20260727-131947` | unsealed Run `execute` |

### 先看状态

```bash
maestro session list
maestro session show <session-id>
```

### 可选处置（三选一）

**A. 补完 Run 再 seal（费力，仅当还要该结论时）**

```bash
# 按 session 内 chain 把 running/pending run 收尾
# 具体命令视 run 状态：brief / done / decide …
maestro run done <run-id> --verdict done   # 示例；以实际 CLI 为准
maestro session seal <session-id> --summary "closed after run harvest"
```

**B. 放弃历史链（推荐：纯卫生）**

- 这些 session 是 **历史分析链**，不阻塞产品功能  
- 可在 `pending-checklist` 标注 “abandoned historical”  
- **不要**为了 seal 去改生产代码  

**C. 维持现状**

- 工程已交付时完全可接受  

### 已 seal 过的

此前 hygiene 已 seal 7 个空闲 session；无需重复。

## 2.2 Knowledge 人审 promote

现状：

```text
knowledge audit: 0 findings
pipeline: 0 corroborated pending · 256 observed pending · 68 promoted
```

- **observed** = 自动观测候选，**不能**用 `--all` 无脑 promote  
- **corroborated** = 0 → 没有“已交叉验证待晋级”批量包  

### 正确流程（按 session）

```bash
# 1) 选一个 sealed session
maestro knowledge review <session-id> --json

# 2) 若有 pending candidates，逐条裁决后 promote
maestro knowledge promote <session-id> \
  --resolve <candidate-id> \
  --as unique|related|duplicate|supersede|conflict \
  --target <knowledge-id> \    # unique 时禁止
  --reason "人工说明：为何晋级"

# 3) 不要
# maestro knowledge promote <session-id> --all   # 对 observed-only 会警告/不安全
```

### 完成定义（P1 knowledge）

- 人审过关心的 session；或明确 **defer** 256 observed  
- audit 仍 0 findings 即可  

### 建议

工程已关时：**defer 即可**。有空再审 T023/T024/B3 相关 session。

---

# 3. P2 — 可选

## 3.1 OSS Scheme C 人审决策

### Agent / 脚本已做的

```bash
python scripts/oss_c_gate.py --quick
# → ready_for_human_c_review=True · blockers=none · secret_scan hits=0
```

### 人必须做的

1. 打开：`docs/research/oss-c-human-review-pack.md`  
2. 勾选决策表：**Stay B** / **Start C** / **Defer**  
3. 若 Start C：  
   - **仅人类**改 visibility / org 策略  
   - **禁止** agent 执行 `gh repo edit --visibility`  

### 完成定义

- 决策写进 review pack 或 issue 备注  
- 非强制；Stay B 完全合法  

## 3.2 Wiki 误报 / “健康度 100”

现状：wiki **92/100**，**4 broken**，目标 `..` 与 `"overview"` 来自 sealed session JSON 文本，是 **LINK_RE 误报**。

| 做法 | 是否推荐 |
|------|----------|
| 改 sealed session JSON 消 broken | **否**（破坏审计） |
| 等 maestro-flow 索引器修正则 | **是**（upstream） |
| 接受 92 + 文档声明 FP | **是**（当前默认） |

### 自检命令

```bash
maestro wiki health
maestro wiki orphans
# broken 细节：maestro wiki graph → brokenLinks
```

### 完成定义

- **产品完成 ≠ wiki 100**  
- 文档已记 FP 政策即可（`TIP-20260810-wiki-kg-false-positive-broken-links`）  

---

# 4. P3 — 研究（无假设则跳过）

## 4.1 何时才做

仅当有 **新可检验假设**，例如：

- 更密 funding 历史 + 新 pin 窗  
- 非 funding 新 alpha 族  
- Elliott 真 multi-run 密封 GO  

## 4.2 怎么做（纪律）

1. **新合同 ID**：`B6-YYYYMMDD-slug` 或 `B6-…`  
2. 写 `docs/research/Candidate-Baseline-6.md`  
3. 产物目录 **新路径**（如 `baseline6/<run_id>/`）  
4. **禁止**：改 B3 YAML thr、改写 `baseline3/` / `B4-OOS-*` / `B5-ABL-*`  
5. **禁止**：为了“看起来还在开发”自动开 **W28** wave 流水线  

## 4.3 无假设时

```text
P3 = SKIP
```

继续只跑 P0 日课即可。

---

# 5. 一页检查清单（复制用）

## 每日（直到 T023 满）

- [ ] UTC 日期确认（未 credit 过今日）  
- [ ] `pwsh -File scripts/path_a_daily.ps1` 或分步 day-session + ingest  
- [ ] `status` 显示 consecutive +1  
- [ ] 未伪造、未 synthetic  

## T023 满当日

- [ ] `status` → target_met / consecutive≥7  
- [ ] `paper_evidence_export.py export`（真实）  
- [ ] `paper_evidence_export.py dry-run`（非 synthetic）  
- [ ] 读 promote 结果；样本不足则继续运营不降门  

## 可选任意日

- [ ] P1：处理或 defer 3 个 seal-blocked session  
- [ ] P1：knowledge review 关心的 session 或 defer 256  
- [ ] P2：填写 OSS C 决策（Stay B / C / Defer）  
- [ ] P3：仅有假设时开 B6+  

## 永远不要

- [ ] 伪造 streak 日历  
- [ ] `--synthetic-full` 当 ops 完成  
- [ ] agent 改 repo visibility  
- [ ] 静默改 B3/B4/B5 冻结  
- [ ] 无假设开 W28  

---

# 6. 命令速查

```bash
# P0 每日
pwsh -File scripts/path_a_daily.ps1
# 或
python scripts/paper_day_session.py
python scripts/paper_day_streak.py ingest
python scripts/paper_day_streak.py status --min-days 7

# P0 T024（streak 满后）
python scripts/paper_evidence_export.py export
python scripts/paper_evidence_export.py dry-run

# P1
maestro session list
maestro session show <id>
maestro session seal <id> --summary "..."
maestro knowledge review <session-id> --json
maestro knowledge promote <session-id> --resolve <cid> --as unique --reason "..."

# P2
python scripts/oss_c_gate.py --quick
# 人读 docs/research/oss-c-human-review-pack.md
maestro wiki health

# 卫生
maestro kg sync
maestro knowledge audit --json
```

---

# 7. 完成判据总表

| 级别 | 判据 | 当前 |
|------|------|------|
| 工程开发完成 | wave 关 + 合同封 + main 干净 | ✅ |
| **P0 ops 完成** | T023≥7 且 T024 真实 dry promote 过样本门 | ❌ 3/7 |
| P1 完成 | 阻塞 session 已处置或明确 defer；knowledge 策略明确 | 可选 |
| P2 完成 | Scheme C 有人审结论；wiki FP 已记录 | 可选 |
| P3 | 无假设 = 自动完成（skip） | ✅ skip |

---

*本手册回答「怎么完成」；工程已不再是瓶颈，日历与诚实运营才是。*
