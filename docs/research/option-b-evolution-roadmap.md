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

## W15 — 数据平面（下一波立项）

| 任务 | done_when |
|------|-----------|
| T031 denser funding/OI 入库（全 pin 或诚实子窗） | meta 覆盖可支撑 B3 重跑 |
| T032 B3 **新** run_meta 重跑（或正式 BLOCKED） | 不覆盖 T026 工件 |
| T033 可选：新信号合同（横截面/阈值修订）— 非 B1 换皮 | 独立 Candidate-Baseline-4+ |

---

## W16 — 保真与 DX（再下一波）

| 任务 | done_when |
|------|-----------|
| T034 Paper 可选吃 OKX 盘口填充（非 HFT） | paper fill 文档 + 开关默认关 |
| T035 策略模板 DX（Jesse 式薄 API） | 1 个模板示范 + 测试 |
| T036 RD-Agent/Qlib **旁路** 进 validation only | 无直连 live |

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
