# OSS 对抗不足点 — 完善改进计划（选项 B / residual-first）

**Date**: 2026-08-11  
**Maestro session**: `20260811-oss-improve-plan-20260811-090327`  
**Sources**:
- [team-swarm-oss-improve-20260811.md](./team-swarm-oss-improve-20260811.md)（对抗共识）
- [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)（已交付 W14–W26）
- [architecture-diagnosis-vs-oss.md](./architecture-diagnosis-vs-oss.md)
- [dual-path-research-os-20260811.md](./dual-path-research-os-20260811.md)

**原则**：不换引擎；不重开已完成波次；只补 **残留厚度 / 接线 / 审计**。

---

## 0. 一句话

> Swarm 列的「要提高」大部分 **已在 W14–W26 + dual-path/IAF/PathB 落地**。  
> 真正要做的是 **5 条 IMP 残留波**：晋级指纹接线、Path B OOS+成本加厚、PIT 审计、多标的研究报告、运维告警。

---

## 1. 诚实 residual 矩阵（对抗项 × 现状）

| Swarm 项 | 状态 | 已交付证据 | 残留（本计划） |
|----------|------|------------|----------------|
| P0 paper_replay 指纹 | **partial** | `promotion_path.py` / `assert_promotion_path_ready` / Elliott 包 | dual-path / path_b_oos / research_os **未 attach**；GO 语言 CI |
| P0 Path B OOS + 成本 | **partial** | `path_b_oos` GO_DISCUSS n=49 | 扩窗/anchored；`fee_slip_grid`+`funding_tca` 附件；仍不 live promote |
| P0 成本 TCA 不松 | **done** | cost_fidelity / funding_tca | 保持；仅随 IMP-01/02 附着 |
| P1 funding/OI 密度 | **mostly_done** | W15 + B3–B5 合同 | 新 alpha 族才再扩；**非本计划主线** |
| P1 Feature Store PIT | **partial** | FeatureStore + as-of meta | **自动化 PIT 回归 vs on_bar** |
| P1 Qlib/RD-Agent 旁路 | **done_core** | `ai_validation_bypass` + CLI | ops 文档/可选打包（低优） |
| P1 IAF 不绑 entry | **done** | `iaf_prune_cpcv` `hard_bind_entry=false` | e2e 回归锁 |
| P2 Jesse DX | **done_core** | `SimpleStrategy` | 可选文档抛光 |
| P2 orderbook paper | **done_core** | `orderbook_fill` + `bbo_max_age` | paper 配置配方（默认关） |
| P2 多标的组合 | **partial** | PortfolioManager / book_risk / multi trades | **端到端 multi-symbol dual-path 报告** |
| P3 可观测 | **partial** | Prometheus 脚手架 | 告警分级 + 会话健康 |

---

## 2. 明确否决（写入计划，不可被 execute 覆盖）

| 否决 | 原因 |
|------|------|
| 整仓迁 Nautilus / Lean / Freqtrade | 无 alpha 证据；B0 已证明六层可 PAPER-GO |
| 多交易所超市 / HFT 做市主线 | 非 OKX paper-first 边界 |
| Optuna / 堆指标当晋级 | 已禁；IAF 仅库 |
| 为抬胜率松 fee/funding | 北极星违背 |
| Path A+B `combined_score` | dual-path 硬约束 |
| IAF hard-bind live/freeze | prune-CPCV 仍 NO-GO |
| 把 W14–W26 当绿野重做 | 浪费；只做 residual |

---

## 3. IMP 波次（可执行，带 done_when）

> 命名 **IMP-***，**不**占用正式 W-number 流水线。  
> 依赖：`blockedBy` 语义写在「依赖」列。

### IMP-01 — 晋级路径接线（P0）

| 项 | 内容 |
|----|------|
| **目标** | 任何 dual-path / Path B / research_os 产出若含 GO 语言，必须带 `execution_path=paper_replay` + `data_fingerprint` |
| **改动面** | `dual_path_report.py` / `run_dual_path_research_os.py` / `path_b_oos.py` / 相关 scripts；可选 CI 脚本 |
| **依赖** | 无（已有 `attach_promotion_path`） |
| **done_when** | ① 报告 JSON 含 `checks.promotion_path` 或顶层 fingerprint；② 单元测试：缺 fingerprint 时 assert 失败；③ 文档 reproduce 命令更新 |
| **非目标** | 不改 live promote；不强制 Path B 变 PAPER-GO |
| **验收命令** | `python -m pytest tests/unit/test_promotion_path.py tests/unit/test_dual_path_* -q` + 生成一份 sample report 断言 fingerprint present |

### IMP-02 — Path B OOS 加厚 + 成本附件（P0）

| 项 | 内容 |
|----|------|
| **目标** | 多窗 OOS 更稳；诚实 n_trials 保留；附 fee×slip / funding_tca 叙事；仍 `promotion_eligible=false` |
| **改动面** | `path_b_oos.py`、`run_path_b_oos.py`、docs pin 表 |
| **依赖** | IMP-01（报告可 attach promotion_path）建议串行，可并行开发后合并 |
| **done_when** | ① `n_windows≥6` 或 anchored+rolling 双模式对比产物；② 报告含 `cost_attachment`（fee_slip_grid 和/或 funding_tca 结构）；③ `research_go∈{GO_DISCUSS,NO-GO}` 且 underreported 门有效；④ 单测覆盖 cost attach + 扩窗 |
| **非目标** | 不因 median excess 小而松门；不 live promote |
| **验收命令** | `python scripts/run_path_b_oos.py --n-windows 6 --out data/paper_replay/dual_path/path_b_oos_v2.json` + focused pytest |

### IMP-03 — Feature Store PIT 自动化审计（P1）

| 项 | 内容 |
|----|------|
| **目标** | 防止未来函数：FeatureStore / meta as-of 与策略 `on_bar` 特征时间点一致 |
| **改动面** | `tests/unit/test_feature_store_pit*.py` 或 `quantflow/data/` 审计 helper；可选 CLI `validate --method pit_audit` |
| **依赖** | 无 |
| **done_when** | ① 构造泄漏用例必须失败；② 正常 as-of 用例通过；③ 文档写明审计范围（OHLCV 因子 + funding/OI 若启用） |
| **非目标** | 不重写 FeatureStore 存储格式 |
| **验收命令** | `python -m pytest tests/unit/test_feature_store_pit*.py -q` |

### IMP-04 — 多标的 dual-path 研究报告（P2）

| 项 | 内容 |
|----|------|
| **目标** | 在 OKX 多 symbol 上并列 Path A/B（或 book 预算），**非多所** |
| **改动面** | scripts + 可选 `dual_path_profiles` 多标扩展；复用 PortfolioManager / book_risk |
| **依赖** | IMP-01（指纹）；IMP-02 可选 |
| **done_when** | ① ≥2 symbols 报告 JSON 无 combined_score；② book/portfolio 字段可追溯；③ 单测 synthetic 2-symbol |
| **非目标** | 多交易所；自动 rebalance 实盘 |
| **验收命令** | script smoke + unit tests |

### IMP-05 — 运维告警分级 + 会话健康（P3）

| 项 | 内容 |
|----|------|
| **目标** | 告警 taxonomy（info/warn/critical）与 paper/live 会话健康面板/指标可读 |
| **改动面** | `quantflow/monitoring/` + docs ops |
| **依赖** | 无 |
| **done_when** | ① 告警级别枚举 + 至少 3 类路由文档；② 关键会话健康指标导出或文档化查询；③ 不破坏现有 Prometheus 路径 |
| **非目标** | 完整 Grafana 大盘美化 |
| **验收命令** | unit / smoke + docs |

### 可选低优（不阻塞主线）

| ID | 内容 | 何时做 |
|----|------|--------|
| IMP-06 | IAF hard_bind e2e 回归锁进 dual-path suite | **landed 2026-08-11** (`tests/unit/test_imp06_hard_bind_lock.py`) |
| IMP-07 | AI bypass ops 文档 + 离线 job 配方 | 有人要跑 RD-Agent 时 |
| IMP-08 | SimpleStrategy catalog 抛光 | **partial 2026-08-11** (catalog+yaml description) |
| IMP-09 | paper_replay orderbook_fill 推荐 overlay YAML | 保真实验时 |

---

## 4. 建议执行顺序与并行

```text
IMP-01 (P0 指纹接线) ──┬──► IMP-02 (P0 Path B 加厚)
                       │
IMP-03 (P1 PIT)  ──────┤（可与 01 并行）
                       │
                       └──► IMP-04 (P2 multi-symbol report)
IMP-05 (P3 ops)  ──────────────────────────► 任意空窗
```

| 波次 | 建议工时量级 | 风险 |
|------|--------------|------|
| IMP-01 | 0.5–1 天 | 低：API 已存在 |
| IMP-02 | 1–2 天 | 中：OOS 数值可能更差（诚实上报） |
| IMP-03 | 1 天 | 中：边界 case |
| IMP-04 | 1–2 天 | 中：数据/对齐 |
| IMP-05 | 0.5–1 天 | 低 |

---

## 5. 全局验收门（整包）

计划「执行完毕」当且仅当：

1. residual 表中 **partial 主线**（指纹接线、Path B 成本附件、PIT 审计）状态变为 **done** 或 **done_with_concerns**（concern 写明）。  
2. 全库相关单测绿；ruff 目标文件过。  
3. **无** combined_score；**无** IAF hard_bind；**无** 引擎迁移 PR。  
4. `docs/research/pending-checklist.md` 更新 IMP 状态。  
5. Path B 若仍 GO_DISCUSS / CPCV NO-GO，**允许** — 诚实负结果算验收通过。

---

## 6. 与已交付能力的边界（防重复）

| 不要再立项为「新功能」 | 原因 |
|------------------------|------|
| promotion_path 核心库 | W14 已交付 |
| orderbook_fill / BBO poll | W16–W20 已交付 |
| SimpleStrategy | W16 已交付 |
| ai bypass | W16/T036 已交付 |
| denser funding/OI 入库 | W15 已交付 |
| dual-path OS / IAF prune / Path B OOS v1 | 2026-08-11 已交付 |

本计划只做 **接线、加厚、审计、报告面、运维**。

---

## 7. 下一 Session 建议（execute）

```text
Intent: Execute IMP-01 then IMP-02 residual improvement plan
In: docs/research/oss-adversarial-improvement-plan-20260811.md
Out: code + tests + sample reports under data/paper_replay/dual_path/
Constraints: no engine rewrite; no live promote; no combined_score
```

推荐 chain：`execute → post-execute → test → post-test`（或拆两个 session：IMP-01/02 与 IMP-03/04）。

---

## 8. 复现 / 对照命令（当前基线）

```bash
set PYTHONUTF8=1
python scripts/run_path_b_oos.py --n-windows 4 --out data/paper_replay/dual_path/path_b_oos.json
python scripts/run_iaf_prune_cpcv.py --out data/paper_replay/dual_path/iaf_prune_cpcv.json
python -m pytest tests/unit/test_promotion_path.py tests/unit/test_path_b_oos.py tests/unit/test_iaf_prune_cpcv.py -q
```

---

*Plan only. Implementation belongs to a subsequent execute session.*

## 9. Execution status (2026-08-11)

| Wave | Status | Evidence |
|------|--------|----------|
| **IMP-01** | **landed** | `build_dual_path_report` attaches `attachments.promotion_path` + fingerprint; path_b_oos `checks.promotion_path`; honest `execution_path=vectorized`; register gate still refuses vectorized |
| **IMP-02** | **landed** | default `--n-windows 6`; `cost_attachment` fee_slip_grid + funding_tca; optional `--compare-modes`; pin `path_b_oos_v2.json` GO_DISCUSS n_trials=69 |

Reproduce:

```bash
set PYTHONUTF8=1
python scripts/run_path_b_oos.py --n-windows 6 --out data/paper_replay/dual_path/path_b_oos_v2.json
python -m pytest tests/unit/test_dual_path_report.py tests/unit/test_path_b_oos.py -q
```

## 10. Execution status IMP-03/04/05 (2026-08-11)

| Wave | Status | Evidence |
|------|--------|----------|
| **IMP-03** | **landed** | `quantflow/data/pit_audit.py` + `tests/unit/test_pit_audit.py` (+ existing `test_feature_store_pit.py`) |
| **IMP-04** | **landed** | `multi_symbol_dual_path.py` + `scripts/run_multi_symbol_dual_path.py` + unit tests; no combined_score |
| **IMP-05** | **landed** | session health gauges + `session_health.py` + `docs/ops/alert-taxonomy-session-health.md` |

```bash
set PYTHONUTF8=1
python -m pytest tests/unit/test_pit_audit.py tests/unit/test_feature_store_pit.py tests/unit/test_multi_symbol_dual_path.py tests/unit/test_session_health.py -q
python scripts/run_multi_symbol_dual_path.py --symbols BTC/USDT,ETH/USDT
```

