# 选项 B — 定向演进路线图（不换引擎）

**Decided**: 2026-08-10  
**Parent**: [architecture-diagnosis-vs-oss.md](./architecture-diagnosis-vs-oss.md)  
**Rejected**: (C) Nautilus/Freqtrade/Lean 大换血  
**Default alternative**: (A) 纯运营 — 本文件仅在选择 **B** 时执行  

---

## 原则

1. **保留** 六层 + TradingSession + fail-closed 成本/paper 门。  
2. **晋级数字** 必须以 **paper_replay / 事件路径** 为权威；VectorBT/BacktestEngine 仅筛选。  
3. **不**为 win_rate 松门；不默认开 RP/checkpoint。  
4. 新研究 = **新合同 + 新 run_meta**，禁静默覆盖 B0–B3 冻结。

---

## W14 — 晋级路径纪律（本波交付）

| 交付 | 状态 |
|------|------|
| `promotion_path.py` + `assert_promotion_path_ready` | ✅ |
| 接入 `assert_promotion_cost_ready` / registry | ✅ |
| 拒绝 `vectorized` / `backtest_engine` 单独 GO | ✅ |
| 要求 `data_fingerprint`（T011 精神） | ✅ |
| 单测 | ✅ |
| 本路线图 | ✅ |

### 报告最小字段（register / GO）

```json
{
  "decision": "GO",
  "fee_slip_grid": ["…"],
  "funding_tca": {"mode": "…"},
  "execution_path": "paper_replay",
  "data_fingerprint": {"aggregate": "…"}
}
```

或 `attach_promotion_path(report, execution_path="paper_replay", data_fingerprint=…)`。

Legacy 诊断可 `require_execution_path=False`（**不得**用于生产 register）。

---

## W15 — 数据平面

| 任务 | done_when | 状态 |
|------|-----------|------|
| T031 denser funding/OI 入库 | merge 315 funding / 1073 OI；窗延至 2024→2026-08 | ✅ |
| T032 B3 **新** run_meta 重跑 | `baseline3/20260810_w15/`；**KEEP_B0**；0 funding trades | ✅ |
| T033 可选：新信号合同（阈值/横截面） | funding 族已独立交付 **B4-OOS / B5-ABL**（均 KEEP_B0）；其它 alpha 仍 optional | ⏳ optional（B4/B5 已封） |

详情：[baseline3-w15-rerun.md](./baseline3-w15-rerun.md)

---

## W16 — 保真与 DX

| 任务 | done_when | 状态 |
|------|-----------|------|
| T034 Paper 可选 BBO 盘口填充（非 HFT） | `orderbook_fill` 默认关 + overlay + 测试 | ✅ |
| T035 策略模板 DX（Jesse 式薄 API） | `SimpleStrategy` + catalog `simple` + 测试 | ✅ |
| T036 RD-Agent/Qlib **旁路** 进 validation only | `ai bypass` + live stamp block + tests | ✅ |

详情：[t036-rdagent-validation-bypass.md](./t036-rdagent-validation-bypass.md)

## OSS uplift (post-W16)

| 任务 | done_when | 状态 |
|------|-----------|------|
| PauseReasonSet + KillSwitch 挂载 | 多源暂停原因 | ✅ |
| Paper BBO `bbo_max_age_sec` | 默认 0；overlay 示例 5s | ✅ |
| Ghost position report | 纯函数对账，不自动平仓 | ✅ |
| Preflight 磁盘余量 | warn-only | ✅ |

详情：[oss-uplift-pause-bbo-ghost.md](./oss-uplift-pause-bbo-ghost.md) · [oss-binance-deribit-btc-learnings.md](./oss-binance-deribit-btc-learnings.md)

详情：[w16-paper-fill-and-strategy-dx.md](./w16-paper-fill-and-strategy-dx.md)

---

## W17 — 小团队接近行业领先（研究，无代码）

| 交付 | 状态 |
|------|------|
| wave / book / factor 三审计（teammate） | ✅ |
| smart-search 外部证据（gap_check closed） | ✅ |
| 总纲 [w17-small-team-edge.md](./w17-small-team-edge.md) | ✅ |
| 波浪边界 [w17-wave-repaint-boundary.md](./w17-wave-repaint-boundary.md) | ✅ |
| 防未来+因子 [w17-antifuture-and-factors.md](./w17-antifuture-and-factors.md) | ✅ |
| 盘口小步 [w17-orderbook-microstructure.md](./w17-orderbook-microstructure.md) | ✅ |

### 收敛结论（执行优先级）

1. **保真 > 新 alpha**：pivot 真价 / 确认 pivot / consensus 显式 / BBO feed。  
2. **死代码解锁**：`update_orderbook` 缺生产 caller（W16 fill 已写）。  
3. **因子先接线休眠五件套**，再谈 Ichimoku/CVD。  
4. **波浪 = 规则状态机 + 风控几何**，PROGRESSIVE 交易须确认 pivot。  

### W18 — Wave + BBO + Factors（组合交付）

| 切片 | 内容 | 状态 |
|------|------|------|
| **W18a** | 真价 pivot + confirmed-only + degraded 显式 | ✅ |
| **W18b** | bar low/high → `ExecutionEngine.update_orderbook` | ✅ |
| **W18c** | 休眠因子暴露 + 口径拆分（core/extended/wave） | ✅ |
| 测试 | `test_w18_wave_bbo_factors` + 相关 66 passed | ✅ |

详情：[w18-wave-bbo-factors.md](./w18-wave-bbo-factors.md)

### W19 — Invalidation + ticker BBO + volume factors

| 切片 | 内容 | 状态 |
|------|------|------|
| **W19a** | Invalidation 接线 + RSI 参考点 + save keep-first | ✅ |
| **W19b** | `set_bbo_source` / `push_ticker_bbo`（默认 bar_proxy） | ✅ |
| **W19c** | session_vwap + obv_slope | ✅ |
| 测试 | `test_w19_*` 等 92 passed | ✅ |

详情：[w19-invalidation-bbo-volume.md](./w19-invalidation-bbo-volume.md)

### W20 — BBO poll + CVD proxy + Elliott WFO smoke

| 切片 | 内容 | 状态 |
|------|------|------|
| **W20a** | `bbo_poll_enabled` 默认关；ticker poll → push | ✅ |
| **W20b** | `cvd_proxy` bar 级量差近似（非 tape CVD） | ✅ |
| **W20c** | `elliott_wave_wfo_smoke`（vectorized_smoke，禁 GO） | ✅ |
| 测试 | `test_w20_*` 等 34 passed | ✅ |

详情：[w20-bbo-poll-cvd-wfo.md](./w20-bbo-poll-cvd-wfo.md)

### W21 — Funding risk gate + Elliott paper_replay + trades CVD

| 切片 | 内容 | 状态 |
|------|------|------|
| **W21a** | funding risk gate → pause / optional KillSwitch（默认关） | ✅ |
| **W21b** | `liu_yudong_wave` paper_replay smoke（禁 auto-GO） | ✅ |
| **W21c** | `fetch_trades` + `cvd_from_trades` 脚手架 | ✅ |
| 测试 | `test_w21_*` 等 23 passed | ✅ |

详情：[w21-funding-paper-cvd.md](./w21-funding-paper-cvd.md)

### W22 — Trades CVD store + Elliott contract + funding/B3 tracks

| 切片 | 内容 | 状态 |
|------|------|------|
| **W22a** | `TradesStore` + FeatureStore CVD 列（proxy 回退） | ✅ |
| **W22b** | Elliott paper_replay 合同包 + fingerprint（W14 path pass） | ✅ |
| **W22c** | funding risk gate ≠ B3 entry_threshold 分轨文档 | ✅ |
| 测试 | `test_w22_*` 等 18 passed | ✅ |

详情：[w22-trades-contract-funding-tracks.md](./w22-trades-contract-funding-tracks.md)

### W23 — Trades ingest + Elliott cost-grid + B4 draft

| 切片 | 内容 | 状态 |
|------|------|------|
| **W23a** | `TradesIngestLoop` poll/push → TradesStore（默认关） | ✅ |
| **W23b** | Elliott cost-grid package（fee×slip + funding_tca 结构；禁 GO） | ✅ |
| **W23c** | B4 funding 合同草稿 thr=0.0004 + overlay（不改 B3） | ✅ |
| 测试 | `test_w23_*` 等 15 passed | ✅ |

详情：[w23-trades-cost-b4.md](./w23-trades-cost-b4.md)

### W24 — B4 runner + Elliott reseat + watch_trades

| 切片 | 内容 | 状态 |
|------|------|------|
| **W24a** | `run_baseline4_challenger.py` → `baseline4/` only（禁 baseline3） | ✅ |
| **W24b** | Elliott fee×slip **paper_replay reseat**（默认；proxy 可选） | ✅ |
| **W24c** | `DataFetcher.watch_trades` + ingest attach（无 WS 则 poll） | ✅ |
| 测试 | `test_w24_*` 等 15 passed | ✅ |

详情：[w24-b4-reseat-watch.md](./w24-b4-reseat-watch.md)

### W25 — B4 meta-window + Elliott assert + multi-symbol trades

| 切片 | 内容 | 状态 |
|------|------|------|
| **W25a** | B4 `--meta-window` + 独立 `run_id`（禁 baseline3） | ✅ |
| **W25b** | `assert_elliott_cost_package.py` 一键结构门 | ✅ |
| **W25c** | `multi_symbol_trades` coordinator | ✅ |
| 测试 | `test_w25_*` 5 passed | ✅ |

详情：[w25-meta-assert-multi.md](./w25-meta-assert-multi.md)

### W26 — B4 freeze + CLI assert-elliott + trades multi overlay

| 切片 | 内容 | 状态 |
|------|------|------|
| **W26a** | B4 adjudication freeze 模板 + freeze 脚本/CLI（禁 GO） | ✅ |
| **W26b** | `quantflow assert-elliott` CLI 接线 | ✅ |
| **W26c** | `paper_trades_multi_overlay.yaml` | ✅ |
| 测试 | `test_w26_*` 6 passed | ✅ |

详情：[w26-freeze-cli-overlay.md](./w26-freeze-cli-overlay.md)

### W27 — Option B 工程 wave 轨道收口

| 切片 | 内容 | 状态 |
|------|------|------|
| **W27a** | 声明 **无新工程 wave 切片**（W17–W26 闭环） | ✅ |
| **W27b** | 残留仅运营：T023 墙钟 / 真实 paper promote 证据 | ✅ |
| **W27c** | 索引文档 [w27-wave-track-close.md](./w27-wave-track-close.md) | ✅ |

**停止条件已满足**：roadmap 不再列出 `W28+ 工程候选`。后续若人类立项新合同（如 B4 全量 OOS），以 **独立合同 ID** 开启，不自动续 W-number 流水线。

并行运营（**非 wave**）— **待办总表**: [pending-checklist.md](./pending-checklist.md)

| 残留 | 状态 |
|------|------|
| **T023** 墙钟 | **3/7** consecutive（UTC 08-08…08-10）；见 [t023-wall-clock-status.md](./t023-wall-clock-status.md) |
| **B4 full OOS** | 独立合同 **B4-OOS-20260810** → **KEEP_B0**；见 [Candidate-Baseline-4-results.md](./Candidate-Baseline-4-results.md) |
| **B5 EMA/OI ablation** | 独立合同 **B5-ABL-20260810** → **KEEP_B0**（OI-off 有成交但 −6%）；见 [Candidate-Baseline-5-results.md](./Candidate-Baseline-5-results.md) |
| 真实 paper promote | 仍待 consecutive≥7 + fills（T024） |

---

## 明确不做（B 边界）

- 替换执行核为 Nautilus/Lean  
- 多交易所适配器超市  
- Optuna/Hyperopt 作为晋级主路径  
- 默认 `portfolio_optimization` / checkpoint / recon = true  
- 改 GitHub visibility  

---

## 与运营残留

| 残留 | 关系 |
|------|------|
| T023 墙钟 | **并行**；B 不替代日课 |
| 真实 promote evidence | 仍依赖 7 日 + fills；路径门额外要求 paper_replay 出处 |

---

## 命令

```bash
# 单测 W14
pytest tests/unit/test_promotion_path.py tests/unit/test_cost_fidelity.py tests/unit/test_ai_training_registry.py -q
```

*Option B: evolve the research path, keep the OS.*
