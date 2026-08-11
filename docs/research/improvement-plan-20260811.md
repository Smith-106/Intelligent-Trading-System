# QuantFlow 完善计划（2026-08-11）

**Status**: approved · **Wave B/C agent pack landed** (Wave A still human)  
**HEAD at approval**: `3619fe2`  
**依据**: [team-swarm-gaps-vs-oss-20260811.md](./team-swarm-gaps-vs-oss-20260811.md) · [pending-checklist.md](./pending-checklist.md) · 性能复验  

---

## 0. 北极星与硬约束

| 锁定 | 含义 |
|------|------|
| **不重写引擎** | 禁止整仓迁 Nautilus / Lean / Freqtrade |
| **不 combined_score** | Path A / Path B 分列 |
| **不 live promote** | `promotion_eligible=false` 至 paper 样本门 + 人类授权 |
| **不改 B0/B3–B5 冻结** | 新信号必须 **新合同 ID** |
| **不自动开 W28** | residual 小包交付 |
| **T023 诚实墙钟** | 不回填 / 不伪造 streak 日 |

**精英路径**:

```text
不换引擎 → T023/T024 日历 → funding/OI 密历史 → paper BBO 会话接线
         → 可选 book risk paper → 可选 MC/CI/RD-Agent/DX
```

---

## 1. 现状快照

| 面 | 状态 |
|----|------|
| dual-path / Path B OOS | Path B val **NO-GO** · OOS **GO_DISCUSS** |
| 性能面板 | shared_RP **+5.14%** PAPER-GO · overlay **+47pp** |
| IMP-01…07/09 | **landed** · IMP-08 **partial** |
| T023 | **4/7**（人 / 日历） |
| T024 | 等 T023≥7 + fills≥20 |

---

## 2. 分波

### Wave A — P0 运营（人为主）

| ID | 事项 | 谁 | done_when |
|----|------|-----|-----------|
| A1 | 每日 `paper_day_session` + streak ingest | **人** | consecutive ≥7 |
| A2 | T023≥7 后 paper_evidence + promote dry-run | **人** | 收据；默认不 live |
| A3 | 同步 wall-clock / checklist | agent/人 | 与 ledger 一致 |

### Wave B — P1 数据与 paper 保真（代码）

| ID | 事项 | done_when |
|----|------|-----------|
| B1 | funding/OI 覆盖探针 + 回填脚本壳 | coverage 报告；不改 B3–B5 阈值 |
| B2 | **B6-META** 合同草案 | 新合同 ID + KEEP 旧冻结 |
| B3 | `paper_day_session` 可选 `--orderbook-fill` + BBO | 默认 OFF；开启时有接线 |
| B4 | orderbook 路径 smoke/unit | 有/无 BBO 回退锁 |

### Wave C — 晋级纪律

| ID | 事项 | done_when |
|----|------|-----------|
| C1 | research JSON fixture：`promotion_eligible is false` | dual_path / path_b 样例锁 |
| C2 | dual-path 可选 MC attach | 默认 OFF（后续空窗） |

### Wave D — 可选（延后）

D1 RD-Agent offline job · D2 book_risk paper smoke · D3 IMP-08 · D4 陈旧 session seal  

---

## 3. 依赖

```text
A1 日课（墙钟） ─────────────► A2 T024
B1 meta ──► B2 合同
B3 BBO ──► B4 测试
C1 fixtures（可与 B 并行）
D* 空窗
```

---

## 4. 全局验收

1. T023 `target_met=True`  
2. T024 dry-run 有结果（过或诚实未过）  
3. B1+B3 交付  
4. C1 测试绿  
5. 无引擎迁移 / combined_score / 冻结静默修改 / 未授权 live  

---

## 5. 明确不做

重扫 overlay w=0.30 · Path B SL4/TP10 · 换引擎 · 多所/HFT · 降 min_fills · Scheme C 改 visibility · KOL 真群  

---

## 6. 本 execute 包（agent）

| 项 | 状态 |
|----|------|
| 本文件 + checklist 链接 | 本 PR |
| B1 coverage/backfill 脚本 | 本 PR |
| B2 B6-META 草案 | 本 PR |
| B3/B4 orderbook-fill 选项 + 测试 | 本 PR |
| C1 fixture 锁 | 本 PR |
| Wave A 日课 | **仍属人** · 不在本 PR 伪造 |

## 7. Landed in this pack (agent)

| ID | Artifact |
|----|----------|
| plan | `docs/research/improvement-plan-20260811.md` |
| B1 | `scripts/meta_funding_oi_coverage.py`, `scripts/backfill_funding_oi.py` |
| B2 | `docs/research/Candidate-Baseline-6-meta.md` |
| B3 | `scripts/paper_day_session.py --orderbook-fill`, `quantflow/config/paper_day_orderbook_overlay.yaml` |
| B4 | `tests/unit/test_paper_day_orderbook_flag.py` |
| C1 | `tests/fixtures/research_promotion/*`, `tests/unit/test_promotion_eligible_fixtures.py` |

**Probe note (local)**: BTC funding n≈270 (~3 months) vs multi-year OHLCV → coverage ≈3%; ETH/SOL meta empty — backfill dry-run recommended before B6 research.

