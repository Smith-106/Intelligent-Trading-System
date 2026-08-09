# Baseline-0 日常 Paper 操作检查清单（T022 Runbook）

**用途**：把 [Candidate Baseline-0](./Candidate-Baseline-0.md) 接到 **Path A 日课**（模拟盘常开），并与 Path B 研究门控、宇宙 admitted、偏差告警、paper 样本门槛对齐。  
**任务**：T022（post-T021 W10）  
**模式**：**paper only** — 本清单 **禁止** `--mode live`

**合同摘要**

| 项 | 值 |
|----|-----|
| 策略 | `trend_following`（`entry_structure=classic`） |
| 标的（默认书） | **admitted ∩ baseline_default**（通常 `BTC/USDT,ETH/USDT,SOL/USDT`） |
| 周期 | `1h` |
| 组合 | 共享账本 + symbol-level RP（**仅 overlay 打开**） |
| 再平衡 | 每 48 个唯一时间戳（~2d @1h） |
| 成本 | taker 0.1% / slip 0.1% |
| Overlay | `quantflow/config/paper_baseline0_overlay.yaml` |
| 研究门控 | [Candidate-Baseline-0-results.md](./Candidate-Baseline-0-results.md) → **PAPER-GO** |

宇宙清单：`quantflow/config/universe.yaml` · 运行时 admitted：`data/paper_replay/universe/admitted.json`（T019）

---

## 0. 两条路径（先选对）

| 路径 | 命令 | nested 方向门？ | 用途 |
|------|------|-----------------|------|
| **A. 日常 paper** | `paper_day_session` / `quantflow run --mode paper` | **否** | 日课、订单/RP 观察、T016 样本累积 |
| **B. 研究 GO** | `python scripts/run_baseline0.py` | **是** | 与 `gate.json` / WFO 对齐 |

> **Path A 的 PnL ≠ Path B 的 gate 数字。** 日课偏差（T017）里的 PnL 带宽只是 **诊断**，不是晋级门。

---

## 1. 一条命令序列（每日默认）

在仓库根目录：

```bash
# 0) 可选：刷新宇宙 SLA → admitted（未过 SLA 永不进默认书）
python scripts/universe_expand_pipeline.py --from-config --write-admitted --dry-run-only

# 1) 一键日课：preflight + 写摘要（含 baseline_snapshot / deviation）
python scripts/paper_day_session.py --alert-on-fail

# 2) 需要挂模拟盘时再启动（前台；Ctrl-C 停）
python scripts/paper_day_session.py --start-run --alert-on-fail

# 3) 可选：快速成本/funding 批门（T015）
python scripts/paper_day_session.py --batch-gate --alert-on-fail
```

**退出码**：`0` = 可继续；非 0 = 先修 preflight / batch_gate，再跑 paper。

等价手搓（与 day-session 相同合同）：

```bash
python scripts/preflight_baseline0_paper.py
quantflow run --mode paper --strategy trend_following \
  --symbols BTC/USDT,ETH/USDT,SOL/USDT --timeframe 1h --interval 60 \
  --capital 100000 --config quantflow/config/paper_baseline0_overlay.yaml
```

> 标的列表优先跟 **admitted ∩ baseline_default**（`universe_config.baseline_symbols_csv()`）。冷启动无 admitted 时回落三币默认。

---

## 2. 启动前 Pre-flight

### 2.1 环境

- [ ] 仓库根目录
- [ ] `python -c "import quantflow"` 可用（0.5.x）
- [ ] **禁止** live；有 OKX key 也必须 `--mode paper`

### 2.2 数据与宇宙

- [ ] 1h Parquet：默认书内各币有足够 bar（preflight：bars/age/quality）
- [ ] （建议）`admitted.json` 存在且三币 `sla_pass`（T019）
- [ ] 最新 bar 建议 &lt; 48h（与 SLA / preflight 一致）

```bash
python scripts/universe_expand_pipeline.py --from-config --write-admitted --dry-run-only
# 不足时：
quantflow download --symbol BTC/USDT --timeframe 1h
# … ETH / SOL 同理
```

### 2.3 Overlay 合同（RP 只在此打开）

- [ ] `default.yaml` 里 `portfolio_optimization.enabled` **保持 false**
- [ ] Overlay：

```yaml
execution.mode: paper
execution.taker_fee: 0.001
execution.slippage: 0.001
risk.portfolio_optimization.enabled: true
risk.portfolio_optimization.method: risk_parity
risk.portfolio_optimization.level: symbol
risk.portfolio_optimization.rebalance_every_n_bars: 48
```

### 2.4 paper_readiness（T016 — promote 用，日课先知情）

默认（`default.yaml` → `risk.paper_readiness`）：

| 字段 | 默认 |
|------|------|
| `enabled` | true |
| `min_paper_days` | 7.0 |
| `min_fills` | 20 |
| `require_evidence` | true |

日课 **不**自动 promote。凑样本后见 §6 / T024。

---

## 3. 日课摘要里有什么（T004 / T017 / T019）

`data/paper_sessions/latest.json`（及带时间戳的 `day_session_*.json`）应可读：

| 块 | 含义 |
|----|------|
| `status` | `ok` / preflight 失败 / `baseline_deviation_*` |
| `contract.symbols` | 本日书（应与 admitted 默认书一致） |
| `baseline_snapshot` | B0 gate decision、窗、metrics（Path B 快照） |
| `deviation` | T017：合同健康 + 可选 PnL 诊断；`path_a_ne_path_b: true` |
| `commands` | 可复制的 run / research / batch_gate 命令 |

**告警**（`--alert-on-fail`）：`status != ok` 或 `deviation.should_alert` 时打印并 best-effort `send_alert`。

**硬健康失败**（缺 `gate.json` / decision 非 PAPER-GO）→ 停扩容，先查 Path B 工件。  
**软诊断**（PnL 带宽）→ 只记 ops review，**不当** NO-GO。

---

## 4. 运行中 / 停止

### 4.1 健康

- [ ] 进程在；无崩溃环
- [ ] 非长时间 0 bar
- [ ] 无误触 live / 无关掉 fee·slip·RP 却仍称 Baseline-0

### 4.2 红线

- [ ] 禁止 silo RP 收益 vs 本会话 shared-book 对比当结论  
- [ ] 禁止用 Path A 日 PnL 替代 `gate.json`  
- [ ] 禁止 Optuna 热更新参数冒充 B0  

### 4.3 停止

- [ ] `Ctrl+C`；记 start/stop  
- [ ] 注明路径 **A**（本清单默认）

---

## 5. 每周研究复核（Path B）

```bash
python scripts/run_baseline0.py --skip-full   # 或全量
# 查 data/paper_replay/baseline0/gate.json → decision 仍为 PAPER-GO
python scripts/funding_tca_report.py         # funding 旁证（T014）
```

五项 checks 任一坏掉 → **停日常扩容**，走 Wave-C / 新合同，不调参硬扛。

---

## 6. 与 T016 paper_evidence / promote（衔接 T023–T024）

### 6.0 连续日课账本（T023）

```bash
# 跑本日 Path A 并记入 streak
python scripts/paper_day_streak.py ingest --run-day-session
# 仅扫描已有 day_session_*.json
python scripts/paper_day_streak.py status --min-days 7
python scripts/paper_day_streak.py report --min-days 7
```

- 账本：`data/paper_sessions/streak_ledger.json`（**每 UTC 日最多 1 次** credit）
- 严格目标：`consecutive ≥ 7`（`target_met`）— **不伪造日历天**
- 同日多次 run 不重复计数

日课目标之一是攒 **可 attach** 的样本（默认 ≥7 天、≥20 fills）：

1. 从 paper 会话日志/成交导出 `paper_days`、`fills`、起止时间  
2. `ModelRegistry.attach_paper_evidence(model_id, {...})`  
3. `promote_to_live` 仅在 evidence 过门槛后；缺 evidence → **rejected**（fail-closed）  
4. **Live 仍非本清单验收范围**

证据字段最小集：

```json
{
  "paper_days": 7,
  "fills": 20,
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601"
}
```

---

## 7. 可选加固（T021 / T029 — 默认关）

| 能力 | 默认 | 开启前 |
|------|------|--------|
| checkpoint `state.enabled` | false | 先 `python scripts/resilience_drill.py` |
| 周期 reconciliation | false | 同上；确认 MonitoringSink/告警通道 |

**不要**在未演练时把 default.yaml 默认改成 true。

---

## 8. 故障速查

| 现象 | 优先检查 |
|------|----------|
| preflight FAIL | parquet / 年龄 / overlay / default RP 被打开 |
| deviation alert（gate） | `data/paper_replay/baseline0/gate.json` 是否 PAPER-GO |
| 只有单币 | symbols / admitted 书 |
| 与 gate 数字差很多 | 是否在用 Path A 对比 Path B |
| promote 被拒 | paper_evidence 天数/fills（T016） |
| 宇宙 FAIL | `universe_expand_pipeline` reasons；未 admitted 勿进默认书 |

---

## 9. 一页口令

```text
【B0 Paper 日课 · T022】
0) python scripts/universe_expand_pipeline.py --from-config --write-admitted --dry-run-only
1) python scripts/paper_day_session.py --alert-on-fail
2) （可选）python scripts/paper_day_session.py --start-run --alert-on-fail
3) 读 data/paper_sessions/latest.json → status / deviation / baseline_snapshot
4) 禁 live / 禁 Path A=B / 禁零成本解读
5) 周复：python scripts/run_baseline0.py 与 gate.json
6) 样本满：attach paper_evidence（T024）— 仍可不 live
```

---

## 10. 相关文件

| 文件 | 角色 |
|------|------|
| `Candidate-Baseline-0.md` / `-results.md` | 合同与 PAPER-GO |
| `baseline-contract-index.md` | B0–B2（+ 后续 B3）索引 |
| `post-t021-implementation-roadmap.md` | T022–T030 |
| `quantflow/config/paper_baseline0_overlay.yaml` | Path A 配置 |
| `quantflow/config/universe.yaml` | 宇宙清单 |
| `scripts/paper_day_session.py` | 日课编排 |
| `scripts/preflight_baseline0_paper.py` | 预检 |
| `scripts/run_baseline0.py` | Path B |
| `quantflow/strategy/research/day_deviation.py` | 偏差 |
| `quantflow/strategy/validation/paper_readiness.py` | 最短样本门槛 |
