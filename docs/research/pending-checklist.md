# QuantFlow 待完成事项清单（Pending Checklist）

**As of**: 2026-08-10 (UTC)  
**HEAD**: see `main`  
**North star**: cost-aware paper-first research OS — not win-rate  
**Source of truth for ops residual**: [residual-ops-status.md](./residual-ops-status.md) · [t023-wall-clock-status.md](./t023-wall-clock-status.md)  
**P1/P2 hygiene log**: [p1-p2-hygiene-status.md](./p1-p2-hygiene-status.md)  
**Full completeness audit**: [project-completeness-audit-20260810.md](./project-completeness-audit-20260810.md)（工程已关；仅 T023/T024 运营残留）  
**How-to 操作手册**: [how-to-close-p0-p3.md](./how-to-close-p0-p3.md)（P0 日课→T024、P1 seal/knowledge、P2 Scheme C、P3 纪律）  
**市场数据可行性（B0 全量复现）**: [market-data-feasibility-20260810.md](./market-data-feasibility-20260810.md) — PAPER-GO 复现；≠ live  
**顶流/幻方收敛**: [highflyer-convergence-20260810.md](./highflyer-convergence-20260810.md) — vs-BTC 门 + 账本预算 + beta/overlay  
**BTC 降回撤/提超额（2026-08-11）**: [btc-dd-return-optimize-20260811.md](./btc-dd-return-optimize-20260811.md) — primary **w=0.30** taker excess **+47.1pp**（较 w=0.25 **+6.7pp**），maxDD **−1.4pp**

---

## 0. 总览（一眼）

| 优先级 | 类别 | 事项 | 阻塞？ | 谁做 |
|--------|------|------|--------|------|
| **P0** | 运营 | **T023** Path A 日课 streak → **7/7** | 日历墙钟 | 人/每日脚本 |
| **P0** | 运营 | **T024** 真实 paper_evidence + promote（非 dry 演示） | **等 T023≥7** + fills | 人 |
| P1 | 卫生 | 本地敏感文件复核（gitleaks 工作区 2 命中） | 否 | 人 |
| P1 | 卫生 | Maestro 陈旧 session seal（W18…） | 否 | 人/agent |
| P2 | 可选 | bar 数据刷新（age~50h WARN） | 否 | 人 |
| P2 | 可选 | OSS Scheme C 人审包勾选 | 否；**禁 agent 改 visibility** | 人 |
| P3 | 研究 | 新信号合同（仅当有假设） | 否；**独立合同 ID** | 人+agent |
| **DEFER** | 旁路 | **KOL/Discord 真实群接入**（管道已就绪，默认关） | **等智能交易系统主线完成后再做** | 人+agent |
| — | 关闭 | W17–W27 / B1–B5 工程与合同 | **已完成** | — |

**KOL/Discord 冻结存档**: [kol-discord-deferred-plan.md](./kol-discord-deferred-plan.md) · [kol-member-near-realtime-sync.md](./kol-member-near-realtime-sync.md) · [kol-discord-aggregation.md](./kol-discord-aggregation.md)

**工程 wave 轨道**：**已关闭**（W27）。禁止自动开 W28。  
**Todo 列表 #0–#68**：**已全部 completed**。

---

## 1. P0 — 必须推进（运营，非代码 wave）

### 1.1 T023 — Path A 连续日课

| 字段 | 当前 |
|------|------|
| consecutive | **3 / 7** |
| credited UTC | 2026-08-08, 08-09, **08-10** |
| target_met | **false** |
| 尚缺 | **未来** UTC 日：约 **08-11 … 08-14**（4 天） |
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
| T023 consecutive≥7 | ❌ 3/7 |
| T016 min_fills（默认 ≥20） | 上次真实导出 fills 不足 → reject |

**T023 达标后 checklist**

- [ ] `python scripts/paper_evidence_export.py`（或项目约定入口）导出**真实** session 窗
- [ ] 核对 evidence：`paper_days ≥ 7`、`fills ≥ 20`（以 T016 配置为准）
- [ ] promote dry-run → 预期应能过样本门（仍非 live 验收）
- [ ] 若仍 reject：记录原因（天数/fills/路径指纹），**不**降门限
- [ ] 真实 promote / live：**默认不做**；仅人类明确授权

**完成定义**: 真实（非 synthetic）evidence 包满足 T016 且 dry promote 不再因样本不足 reject  
**诚实约束**: synthetic-full pass **不算** ops 完成

---

## 2. P1 — 建议尽快（卫生 / 会话）

### 2.1 本地敏感面复核 — ✅ 2026-08-10

| 项 | 结果 |
|----|------|
| `.workflow/recovery/**` | gitignore ✅ · untracked · keyword scan clean |
| `data/live_evidence/**` | gitignore ✅ · untracked · **no api keys** (balances/timings only) |
| oss_c_gate secret_scan | hits=0 |

- [x] 确认无密钥入仓  
- [x] 不提交 gitleaks JSON / recovery / live_evidence  

### 2.2 Maestro 陈旧 session — ✅ partial + **DEFER×3**

- [x] 列出 active sessions  
- [x] seal 7 个无阻塞 session（含 w18…）  
- [x] 余 3 个 seal 失败已 **DEFER**（lifecycle command sha256 drift；见 [doable-close-20260810.md](./doable-close-20260810.md)）  
  - `a-b-mr-88-sma200-20260807-101222` / `…101321` / `maestro-arch-iss003-…`  

### 2.3 仓库噪音 — ✅

- [x] `.experts-mode.json` → **`.gitignore`**  
- [x] `git status` 无 paper/recovery staged  

---

## 3. P2 — 可选增强

### 3.1 数据新鲜度 — ✅ attempted 2026-08-10

- [x] BTC/SOL 1h download OK；ETH 曾 connect fail（可再试）  
- [x] **未**伪造 bar / streak  

### 3.2 OSS Scheme C（人审 only） — gate 绿；决策仍属人

- [x] `oss_c_gate --quick` → ready_for_human_c_review=True  
- [ ] 人类决策：Stay B / Start C / Defer  
- [x] **Agent 未改 visibility**  

### 3.3 文档小对齐 — ✅

- [x] option-b T033 行注明 B4/B5 已封 KEEP  
- [x] `__version__` + CLI Phase → **v0.6.0**  

---

## 4. P3 — 研究合同（仅有新假设时）

规则：**独立合同 ID**（`B6-…` / 日期戳），**禁止**静默改 B3/B4/B5 冻结包与默认 YAML。

| 若假设是… | 建议合同形态 | 禁做 |
|-----------|--------------|------|
| 更密 funding 历史再 pin | 新 run_id + denser meta；可仍 B4/B5 族 | 改 thr 冒充旧合同 GO |
| 非 funding 新 alpha | 新 Baseline-N 合同 + challenger | Optuna 当晋级主路径 |
| Elliott 真 GO | 密封 multi-run + cost grid + human | proxy/reseat 包当 GO |
| 组合/多标的 funding | 新 book 合同 | 默认打开 portfolio_optimization |

当前 **无强制** P3 工程项；B5 已回答「EMA/OI 消融」→ KEEP_B0。

---

## 5. 已关闭（勿重开除非回归）

| 轨道 | 状态 |
|------|------|
| ISS-004 / 005 / 006 母题 | 关 |
| T001–T027 主线工程（含 T024 管道） | 关（T023 **墙钟**除外） |
| Option B W17–W27 | 关；无 W28+ 候选 |
| B1–B5 challenger 合同 | 全 **KEEP_B0 冻结** |
| B0 research | **PAPER-GO**（研究候选；≠ live 已 promote） |

---

## 6. 明确不做（边界）

- 替换执行核（Nautilus/Lean/Freqtrade）  
- 多交易所适配器超市  
- Optuna/Hyperopt 作晋级主路径  
- 默认 `portfolio_optimization` / checkpoint / recon = true  
- Agent 改 GitHub visibility  
- 伪造 T023 日历天 / synthetic 冒充真实 promote  
- 静默改 B3 `entry_threshold=0.001` 或重写 `baseline3/` / `B4-OOS-*` / `B5-ABL-*`  

---

## 7. 建议执行顺序（滚动 2 周）

| 日序（UTC） | 动作 |
|-------------|------|
| 每天 | §1.1 Path A + streak（直到 7/7） |
| 任意空档 | §2.1 敏感面 · §2.2 seal session · §2.3 噪音 |
| consecutive 达 7 当日 | §1.2 evidence export + dry promote |
| 仅人类决策后 | §3.2 Scheme C 或 live 相关 |
| 有新研究假设时 | §4 新合同 ID |

---

## 8. 一键命令速查

```bash
# --- 每日 T023 ---
python scripts/paper_day_session.py
python scripts/paper_day_streak.py ingest
python scripts/paper_day_streak.py status --min-days 7

# --- T023 满后 T024 ---
python scripts/paper_evidence_export.py
# promote dry-run：按 residual-ops / T024 文档入口

# --- 合同复现（已冻结，勿当新 GO）---
python scripts/run_baseline4_full_oos.py --run-id B4-OOS-20260810
python scripts/run_baseline5_ablation_oos.py --run-id B5-ABL-20260810

# --- 卫生 ---
python scripts/oss_c_gate.py --quick
git status -sb
```

---

## 9. 变更日志

| 日期 | 说明 |
|------|------|
| 2026-08-10 | 初版：T023=3/7；B4/B5 KEEP；wave 关；P0–P3 分层 |
| 2026-08-10 | P1/P2 hygiene：ignore experts-mode；seal 7 sessions；v0.6 文案；download 尝试；见 p1-p2-hygiene-status.md |
| 2026-08-10 | 全量 completeness audit + kg sync：无强制工程缺口；见 project-completeness-audit-20260810.md |
| 2026-08-10 | **doable-close**：同日 Path A 刷新仍 3/7；3 session DEFER；knowledge observed DEFER；oss_c 再确认；见 doable-close-20260810.md |
| 2026-08-11 | **KOL/Discord DEFER**：管道/参考权重/准实时/通知触发已入库，真实群接入冻结至主线完成；见 [kol-discord-deferred-plan.md](./kol-discord-deferred-plan.md) |
| 2026-08-11 | **BTC overlay 再优化**：primary w=0.30；DD 网格脚本；holdout OOS+；见 [btc-dd-return-optimize-20260811.md](./btc-dd-return-optimize-20260811.md) |
| 2026-08-11 | **IAF 指标/防未来**：12 正交振荡因子 + causal 单测 + 负向 shift 扫描；**非正式 W-number**；见 [iaf-indicators-anti-leak-20260811.md](./iaf-indicators-anti-leak-20260811.md) |
| 2026-08-11 | **Team-swarm 对抗设计**：双路径 overlay/TPSL + 因果/门禁共识；见 [team-swarm-iaf-tpsl-adversarial-20260811.md](./team-swarm-iaf-tpsl-adversarial-20260811.md) |
| 2026-08-11 | **Dual-path Research OS**：统一并列报告/IAF prune/诚实 n_trials/因果预检 **已落地**；见 [dual-path-research-os-20260811.md](./dual-path-research-os-20260811.md) |
| 2026-08-11 | **TPSL+R:R**：离散 dual-MA 止盈止损；推荐 SL4%/TP10% min_rr2.5 → excess +3.98pp maxDD21% payoff2.5；见 [iaf-tpsl-rr-20260811.md](./iaf-tpsl-rr-20260811.md) |

*本清单描述「还剩什么」，不创造新的 W-number 流水线。*
| 2026-08-11 | **Path B multi-window OOS + IAF prune→CPCV**：honest n_trials / GO_DISCUSS only; IAF never hard-bind；knowledge 10/10 promoted |
