# QuantFlow 待完成事项清单（Pending Checklist）

**As of**: 2026-08-11（全面盘点刷新）  
**HEAD**: `963952d` · **版本**: **v0.7.0**  
**North star**: cost-aware paper-first research OS — not win-rate  
**工作树**: 干净（`main` = origin）

| 权威文档 | 用途 |
|----------|------|
| [residual-ops-status.md](./residual-ops-status.md) | 运营残留总览 |
| [t023-wall-clock-status.md](./t023-wall-clock-status.md) · [t023-wall-clock-calendar.md](./t023-wall-clock-calendar.md) | T023 墙钟 |
| [how-to-close-p0-p3.md](./how-to-close-p0-p3.md) | P0→T024 / P1–P3 操作手册 |
| [oss-adversarial-improvement-plan-20260811.md](./oss-adversarial-improvement-plan-20260811.md) | IMP residual（01–05 **landed**） |
| [knowledge-maintenance-20260811.md](./knowledge-maintenance-20260811.md) | 知识库/wiki/kg 维护回执 |
| [docs/release/v0.7.0.md](../release/v0.7.0.md) | 发布说明 |

---

## 0. 总览（一眼）

| 优先级 | 类别 | 事项 | 状态 | 阻塞？ | 谁做 |
|--------|------|------|------|--------|------|
| **P0** | 运营 | **T023** Path A 日课 streak → **7/7** | **4/7** | 日历墙钟 | **人** / 每日脚本 |
| **P0** | 运营 | **T024** 真实 paper_evidence + promote dry-run | 管道✅ · 未验收 | **等 T023≥7** + fills≥20 | **人** |
| P1 | 卫生 | 本地敏感面 / gitleaks 复核 | ✅ 2026-08-10 | — | — |
| P1 | 会话 | 3 个陈旧 `running` session seal | **DEFER** | lifecycle drift | 人/可选 |
| P2 | 可选 | bar 数据刷新 | ✅ 尝试过；可再刷 | 否 | 人 |
| P2 | 人审 | OSS Scheme C 决策（Stay B / Start C / Defer） | gate 绿 · **未决策** | 否；**禁 agent 改 visibility** | **人** |
| P3 | 研究 | 新信号合同（仅当有假设） | 空闲 | 否；**独立合同 ID** | 人+agent |
| 可选 | 工程 | IMP-06…09 polish | **06/07/09 landed · 08 partial** | 否 | — |
| P1 | 工程 | **完善计划 Wave B/C**（meta/BBO/CI） | **in progress → land this commit** | 否 | agent |
| **DEFER** | 旁路 | KOL/Discord 真实群接入 | 管道就绪默认关 | 主线后 | 人+agent |
| — | 关闭 | W17–W27 / B1–B5 / IMP-01…05 / v0.7.0 | **已完成** | — | — |

**工程 wave 轨道**：**已关闭**（W27）。**禁止自动开 W28**。  
**Todo 历史列表 #0–#68**：**已全部 completed**。  
**Issues open-like**：**0**。

**KOL/Discord 冻结存档**: [kol-discord-deferred-plan.md](./kol-discord-deferred-plan.md) · [kol-member-near-realtime-sync.md](./kol-member-near-realtime-sync.md) · [kol-discord-aggregation.md](./kol-discord-aggregation.md)

---

## 1. P0 — 必须推进（运营，非代码 wave）

### 1.1 T023 — Path A 连续日课

| 字段 | 当前（实测 2026-08-11） |
|------|------------------------|
| consecutive | **4 / 7** |
| credited UTC | 2026-08-08, 08-09, 08-10, **08-11** |
| target_met | **false** |
| 7d 窗缺失 | 08-05, 08-06, 08-07 |
| 尚缺 | 约 **3** 个**未来** UTC 日（不可回填） |
| 禁止 | 回填/伪造 08-04…08-07 或未来日 |

**每日 checklist（UTC 日切后执行一次）**

- [ ] `python scripts/paper_day_session.py`（preflight + summary；默认不 `--start-run`）
- [ ] 可选：`--start-run` 仅当操作员在场要挂 paper
- [ ] `python scripts/paper_day_streak.py ingest`
- [ ] `python scripts/paper_day_streak.py status --min-days 7`
- [ ] 确认当日 UTC 进入 `streak_ledger.json` 且 `consecutive` +1
- [ ] 可选：`quantflow download` 若 preflight 持续 WARN bar age

**完成定义**: `target_met_consecutive == true`（consecutive ≥ 7）  
**文档**: [t023-wall-clock-status.md](./t023-wall-clock-status.md) · [t023-wall-clock-calendar.md](./t023-wall-clock-calendar.md)

### 1.2 T024 — 真实 promote 证据链

| 前置 | 状态 |
|------|------|
| T024 管道（export + dry-run） | ✅ 已有 |
| T023 consecutive≥7 | ❌ **4/7** |
| T016 min_fills（默认 ≥20） | 上次真实导出 fills 不足 → reject |
| live promote | **默认不做**（仅人类明确授权） |

**T023 达标后 checklist**

- [ ] `python scripts/paper_evidence_export.py`（或项目约定入口）导出**真实** session 窗
- [ ] 核对 evidence：`paper_days ≥ 7`、`fills ≥ 20`（以 T016 配置为准）
- [ ] promote dry-run → 预期应能过样本门（仍非 live 验收）
- [ ] 若仍 reject：记录原因（天数/fills/路径指纹），**不**降门限
- [ ] 真实 promote / live：**默认不做**；仅人类明确授权

**完成定义**: 真实（非 synthetic）evidence 包满足 T016 且 dry promote 不再因样本不足 reject  
**诚实约束**: synthetic-full pass **不算** ops 完成

---

## 2. P1 — 卫生 / 会话

### 2.1 本地敏感面复核 — ✅ 2026-08-10

| 项 | 结果 |
|----|------|
| `.workflow/recovery/**` | gitignore · untracked · keyword scan clean |
| `data/live_evidence/**` | gitignore · untracked · no api keys |
| oss_c_gate secret_scan | hits=0 |
| `.workflow/scratch/**` | **v0.7.0 已从 Git 取消跟踪**（~153 文件） |

- [x] 确认无密钥入仓  
- [x] 不提交 gitleaks JSON / recovery / live_evidence / scratch 运行时  

### 2.2 Maestro 陈旧 session — ✅ partial + **DEFER×3**

仍为 `running`（seal 曾失败 / lifecycle drift；见 [doable-close-20260810.md](./doable-close-20260810.md)）：

| Session ID | Intent（摘要） |
|------------|----------------|
| `a-b-mr-88-sma200-20260807-101222` | 方向门 A/B：mr 88d SMA200 |
| `a-b-mr-88-sma200-20260807-101321` | 同上（重复） |
| `maestro-arch-iss003-004-005-011-20260727-131947` | 旧 ExecutionEngine SRP / ISS 包 |

- [x] 列出 active sessions  
- [x] seal 无阻塞 session（含 w18…）  
- [ ] **可选**：修复 lifecycle 后 seal 上述 3 个（**不阻塞** T023/T024）  
- [x] 其余 session 均为 sealed（~77）

### 2.3 仓库噪音 — ✅（v0.7.0 加固）

- [x] `.experts-mode.json` → gitignore  
- [x] `.workflow/tmp|archive|scratch|search-daemon*` → gitignore  
- [x] `git status` 干净  

---

## 3. P2 — 可选增强

### 3.1 数据新鲜度

- [x] BTC/SOL 1h download 曾成功；ETH 曾 connect fail（可再试）  
- [x] **未**伪造 bar / streak  
- [ ] 可选：再跑 `quantflow download` 降低 bar age WARN  

### 3.2 OSS Scheme C（人审 only）

- [x] `oss_c_gate --quick` → `ready_for_human_c_review=True`  
- [ ] **人类决策**：Stay B / Start C / Defer  
- [x] **Agent 未改 visibility**  

---

## 4. P3 — 研究（有假设再开）

| 规则 | 说明 |
|------|------|
| 新信号 / 新合同 | **独立合同 ID**，不占用 W28+ 自动流水线 |
| B4/B5 | 已 **KEEP_B0** 封存；不重置 T023 |
| dual-path | Path A / Path B **分轴**；**禁止** `combined_score` |
| 晋级 | research `vectorized` 诚实标签；`promotion_eligible=false` 直至 paper 路径 |

- [ ] 仅当有可检验假设时立项（文档 + 验收命令 + 否决标准）

---

## 5. 可选工程 polish（IMP-06…09 — 非阻塞）

| ID | 内容 | 何时做 | 状态 |
|----|------|--------|------|
| IMP-06 | IAF `hard_bind_entry=false` e2e 锁进 dual-path suite | **landed** | — |
| IMP-07 | AI bypass ops 文档 + 离线 RD-Agent job 配方 | **landed** [rdagent-offline-job-recipe.md](../ops/rdagent-offline-job-recipe.md) | — |
| IMP-08 | SimpleStrategy catalog 抛光 | **partial** (catalog+yaml) | — |
| IMP-09 | paper_replay `orderbook_fill` 推荐 overlay YAML | **landed** [paper-orderbook-fill-recipe.md](../ops/paper-orderbook-fill-recipe.md) | — |

**IMP-01…05**：**全部 landed**（v0.7.0）— 见 [oss-adversarial-improvement-plan-20260811.md](./oss-adversarial-improvement-plan-20260811.md) §9–10。

---

## 6. 已关闭轨道（勿重开）

| 轨道 | 状态 |
|------|------|
| Option B W17–W27 | 关；无 W28+ 候选 |
| B0 PAPER-GO 研究候选 | 合同保留；≠ live |
| B1–B5 / funding 族 | KEEP / 封存 |
| Dual-path Research OS + IAF/TPSL library-only | 落地；不 hard-bind entry |
| IMP-01…05 residual | landed + 测试 + knowledge |
| 知识库/wiki/kg 维护 2026-08-11 | audit 0 findings；kg pass；见 [knowledge-maintenance-20260811.md](./knowledge-maintenance-20260811.md) |
| v0.7.0 release + docs-demo | tag + GH release + public pack sync |
| Issues open | 0 |

**硬约束（持续有效）**

- paper-first · OKX 个人闭环 · 非 HFT  
- 不换引擎（拒绝整仓迁 Nautilus/Lean/Freqtrade）  
- 不引入跨所 / 默认组合优化（`portfolio_optimization.enabled=false`）  
- 不伪造 streak / bar / 样本门  
- `pending_observed` **≠** 自动 promote 队列  

---

## 7. 建议执行顺序

```text
1) [人·每日] T023 日课 → ingest → status          ← 唯一硬路径
2) consecutive ≥ 7
3) [人] T024 真实 evidence + dry promote           ← 仍默认不做 live
4) [人] Scheme C 决策（Stay B / Start C / Defer）
5) [空窗] IMP-06…09 或 seal 3× DEFER session
6) [有假设] 新研究合同（独立 ID）
```

### 7.1 今日最小动作（T023）

```bash
set PYTHONUTF8=1
python scripts/paper_day_session.py
python scripts/paper_day_streak.py ingest
python scripts/paper_day_streak.py status --min-days 7
```

### 7.2 知识面巡检（可选）

```bash
maestro knowledge audit --scope all --json
maestro wiki health
maestro kg sync --json && maestro kg health --json
```

---

## 8. DEFER 明细

| 项 | 原因 | 解冻条件 |
|----|------|----------|
| KOL/Discord 真实群 | 主线优先；管道已就绪默认关 | 主线 ops 稳定 + 明确授权 |
| 3× running session seal | lifecycle command sha drift | 人决定修协议或归档忽略 |
| live promote | 样本门 + 风控 | T023/T024 + 人类授权 |
| 历史 knowledge `pending_observed` 批量 promote | uncorroborated | 逐条人工裁决；见 TIP pending_observed |

---

## 9. 变更日志

| 日期 | 说明 |
|------|------|
| 2026-08-10 | 初版：T023=3/7；B4/B5 KEEP；wave 关；P0–P3 分层 |
| 2026-08-10 | P1/P2 hygiene；doable-close；completeness audit |
| 2026-08-11 | KOL DEFER；BTC overlay；IAF/TPSL；dual-path OS；team-swarm OSS |
| 2026-08-11 | IMP-01…05 landed；v0.7.0 release；scratch untrack；kb maintenance |
| 2026-08-11 | **catalog 修复**：B4/B5 funding overlay 移出 strategies/（不再覆盖 funding_rate）+ IMP-07/09 ops 配方 |
| 2026-08-11 | **经验→结构**：research 公共 API + IMP-06 hard_bind 锁 + Simple DX + learnings knowhow — [README.md](./README.md) |
| 2026-08-11 | **完善计划 execute**：B1 coverage/backfill · B2 B6-META · B3 orderbook-fill · C1 fixtures — [improvement-plan-20260811.md](./improvement-plan-20260811.md) |
| 2026-08-11 | **team-swarm 残差**：相对 OSS 短板 = T023/meta/BBO接线（非换引擎）— [team-swarm-gaps-vs-oss-20260811.md](./team-swarm-gaps-vs-oss-20260811.md) |
| 2026-08-11 | **性能参数复验**：shared_RP +5.14% PAPER-GO · overlay +47pp · PathB NO-GO/GO_DISCUSS — [performance-metrics-verify-20260811.md](./performance-metrics-verify-20260811.md) §8 |
| 2026-08-11 | **性能指标验证**：multi_symbol_replay + B0 PAPER-GO + overlay/PathB 面板 — [performance-metrics-verify-20260811.md](./performance-metrics-verify-20260811.md) |
| 2026-08-11 | **市场能力验证**：dual-path/PathB OOS/multi-symbol/demo pack 全绿跑通；Path B validation NO-GO + OOS GO_DISCUSS 诚实结果 — [market-capability-verify-20260811.md](./market-capability-verify-20260811.md) |
| **2026-08-11** | **T023 日课推进**：day-session + ingest → **4/7**；T024 dry-run 诚实 reject（days=4 fills=0）；bar download 网络失败非阻塞 |
| **2026-08-11** | **全面盘点刷新本清单**：P0 仍仅 T023/T024；P1 敏感面/scratch 关闭；3 session DEFER；IMP-06…09 标可选；知识面健康 |

---

*本清单描述「还剩什么」，不创造新的 W-number 流水线。唯一硬残留是 **T023 日历 streak（4→7）及其后的 T024 真实样本门**。*
