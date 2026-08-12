---
title: 研究 GO 面板导出（L6）：指纹跳过门 + path_semantics + 非 promote 语义
category: research-ops
createdBy: "execute:maestro-20260812-l6-research-go-export"
sourceRef: maestro-20260812-l6-research-go-export-20260812-112502
type: knowhow
status: active
related:
  - DOC-monitoring-sink-protocol
---
# 研究 GO 面板导出（L6 research_go_panel）

## 适用场景

把已封存（sealed）的研究 GO 面板导出为可观测指标 / JSON，供 Ops 查看
PAPER-GO 研究结论，同时**不触发** full-window `multi_symbol_replay` 重跑、
不引入实时 promote 语义、不碰 Grafana 重设计。

## 1. 数据源（SoT）

- **唯一来源**：`data/paper_replay/perf_verify/performance_panel.json`
- 加载器：`quantflow/monitoring/research_go_panel.py`（L6-only）
  - `load_research_go_panel(path=None)` → `ResearchGoPanelSnapshot | None`
  - 默认路径由 `DEFAULT_RESEARCH_GO_PANEL_PATH` 给出，相对路径按仓库根解析
  - **fail-soft**：文件缺失 / JSON 损坏 / 缺 `baseline0_gate` / 缺主数字 → 打
    warning 并返回 `None`，绝不编造指标
- 主字段映射（primary = `baseline0_gate` + `shared_risk_parity`）：
  - `decision` ← `baseline0_gate.decision`（`PAPER-GO`）
  - `primary_mode` ← `baseline0_gate.primary_mode`（`shared_risk_parity`）
  - `full_return_pct` ← `baseline0_gate.metrics.full_return_pct`
  - `full_sharpe` ← `baseline0_gate.metrics.full_sharpe`
  - `full_max_dd_pct` ← `baseline0_gate.metrics.full_max_dd_pct`
  - `full_orders` ← `baseline0_gate.metrics.full_orders`
  - 兜底：gate metrics 缺失时回退 `portfolio_modes[primary_mode]` 等价字段
  - `data_fingerprint_aggregate` / `as_of` 原样保留

## 2. 指纹跳过门（fingerprint gate）

- 封存指纹：**`e4d2797070a49bc0`**
- 策略：`data_fingerprint_aggregate` 仍为 `e4d2797070a49bc0` 且
  `baseline0_match` 全部为 true → **`skip_full_window_rerun`**，只导出封存值，
  不重跑 full-window `multi_symbol_replay`（数据未变，重跑无新增信息）
- 重门（re-gate）：仅当指纹变化时才需手动重跑验证并刷新面板（自动化延后，
  当前为手工流程，见 `runs/*/outputs/fingerprint-status.json`）

## 3. promote 语义（重要）

- **`promotion_eligible` 恒为 `false`**：研究 GO 导出 ≠ 实时 promote。
  面板中 `locks.no_live_promote: true`，导出快照强制
  `promotion_eligible=False`（即使 `promotion_eligible_any_research` 为 true 也
  强制 False），对应 `quantflow_research_go_promotion_eligible` gauge 恒为 0。
- 不发明 `combined_score`；Path A/B 不参与主指标导出。

## 4. path_semantics

快照 JSON 中保留三个键（原样拷贝，缺省为空 dict，不编造叙述）：

- `multi_symbol_replay` — paper_replay virtual book（事件路径），非实盘
- `beta_overlay_dual_path` — vectorized research；promotion_eligible=false
- `parity_note` — parity 仅保证 paper↔live；backtest/vectorized 分离

这些是叙述性标签，**不作为 Prometheus gauge / label** 导出（避免高基数叙事
标签）；仅 `fingerprint` 作为 label 出现在 `quantflow_research_go_decision` 上。

## 5. 指标清单（quantflow_research_go_*）

| 指标名 | 含义 | Label |
|---|---|---|
| `quantflow_research_go_decision` | PAPER-GO=1，其他=0 | primary_mode, decision, fingerprint, promotion_eligible |
| `quantflow_research_go_return_pct` | full-window 收益 % | 同上 |
| `quantflow_research_go_sharpe` | full-window Sharpe | 同上 |
| `quantflow_research_go_max_dd_pct` | full-window 最大回撤 % | 同上 |
| `quantflow_research_go_orders` | full-window 订单数 | 同上 |
| `quantflow_research_go_promotion_eligible` | 恒 0.0（不 promote） | 同上 |
| `quantflow_research_go_as_of_timestamp` | 面板 as_of（unix 秒） | 无 |

`promotion_eligible` label 固定为字符串 `"false"`；不按 symbol 打标（低基数）。

## 6. CLI 用法

```bash
python scripts/export_research_go_panel.py                # 打印 JSON 快照
python scripts/export_research_go_panel.py --push-metrics # 顺带推 Prometheus gauges
python scripts/export_research_go_panel.py --panel <path> # 指定面板文件
```

- 退出码：0 = 成功导出；2 = 面板缺失/无效（fail-soft，输出显式
  `{"loaded": false, ...}` JSON，不 traceback）
- 调用方：`quantflow.monitoring.research_go_panel.load_research_go_panel` +
  `quantflow.monitoring.metrics.update_research_go_panel_metrics`；
  `MonitoringSink.record_research_go_panel`（Protocol/Null/Default 三层）
- **不在热路径**：`TradingSession.on_bar` 不调用本导出；L1-L5 不引入
  monitoring 导入（common/ 接缝保持 Any 类型）

## 7. 非目标（Non-goals）

- Grafana 看板重设计（另行跟进）
- 指纹变化的自动重门流水线（当前手工）
- Path A/B 主序列导出、combined_score、silo 作 primary

## 来源

maestro-20260812-l6-research-go-export session（2026-08-12），plan
ART-002-004（W1-W3），fingerprint-status e4d2797070a49bc0 unchanged。
