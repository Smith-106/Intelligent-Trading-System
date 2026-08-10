# W22 — Trades CVD store + Elliott contract package + funding/B3 tracks

**Date**: 2026-08-10  
**Scope**: W22a + W22b + W22c  
**Parent**: [w21-funding-paper-cvd.md](./w21-funding-paper-cvd.md) · [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Constraint**: no auto-GO; B0/B3 frozen; trades dumps local  

---

## Delivered

### W22a — Trades persistence + FeatureStore CVD

| 项 | 实现 |
|----|------|
| `TradesStore` | Hive `data/trades/{SYMBOL}/year=*/month=*.parquet` |
| `build_cvd_feature_frame` | trades → bar-aligned CVD；否则 `cvd_proxy` |
| `save_cvd_features` | 写入 FeatureStore（keep-first 写保护仍生效） |
| gitignore | `data/trades/` |

```python
from quantflow.data.trades_store import TradesStore, save_cvd_features
from quantflow.data.feature_store import FeatureStore

store = TradesStore("data/trades")
store.save_trades("BTC/USDT", trades_df)
save_cvd_features(FeatureStore("data/features"), "BTC/USDT", ohlcv, trades_df)
```

### W22b — Elliott paper_replay contract package

| 项 | 实现 |
|----|------|
| 模块 | `elliott_paper_replay_contract.py` |
| `run_meta` | `execution_path=paper_replay` + `data_fingerprint` + timestamps |
| `check_promotion_path` | structure **passes** W14 when fingerprint present |
| 输出 | optional `run_meta.json` + `summary.json` |
| 晋级 | `promotion_eligible=false`（仍需 cost grid / streak / human） |

```python
import asyncio
from quantflow.strategy.research.elliott_paper_replay_contract import (
    build_elliott_paper_replay_package,
)
pkg = asyncio.run(build_elliott_paper_replay_package(n_bars=200, output_dir="data/paper_replay/elliott_w22"))
assert pkg.path_check["passed"]
```

### W22c — Funding risk gate ≠ B3 signal threshold

| 轨道 | 含义 | 变更规则 |
|------|------|----------|
| **B3** `funding_rate.entry_threshold=0.001` | 冻结 **信号** 合同；KEEP_B0 | 仅 B4+ 新合同 |
| **Risk** `funding_risk_gate` / `max_funding_rate_abs` | **会话风控**（默认关） | 可独立开关；**不得**改写 B3 裁决 |

文档锚点：`funding_risk_gate.py` 模块 docstring、`RiskConfig` 字段注释、本文件。

---

## Tests

```bash
pytest tests/unit/test_w22_trades_contract_funding_tracks.py \
  tests/unit/test_w21_funding_paper_cvd.py -q
```

**Result**: 18 passed.

---

## Non-goals

- WebSocket trades stream / 生产 tape 仓  
- 自动 `ModelRegistry.register` / promote  
- 静默修改 B3 `entry_threshold` 或 B0 PAPER-GO  

---

*W22 complete when tests green and roadmap §W22 checked.*
