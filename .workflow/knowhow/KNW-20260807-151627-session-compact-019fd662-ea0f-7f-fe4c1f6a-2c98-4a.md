---
title: "Session compact fe4c1f6a-2c98-4af1-a40d-5e9211e96229"
description: "Session compact checkpoint for 019fd662-ea0f-7f7b-801f-4ad3fae9205f"
type: session
created: "2026-08-07T15:16:27.887Z"
tags: [session, compaction, checkpoint, todo, skill]
status: active
sessionId: "019fd662-ea0f-7f7b-801f-4ad3fae9205f"
checkpointId: "fe4c1f6a-2c98-4af1-a40d-5e9211e96229"
previousCheckpointId: "4ce3d42c-1912-43be-82fb-428731ea0e4d"
---

# Session Compact Checkpoint

## Checkpoint Metadata

- Session ID: `019fd662-ea0f-7f7b-801f-4ad3fae9205f`
- Checkpoint ID: `fe4c1f6a-2c98-4af1-a40d-5e9211e96229`
- Previous Checkpoint: `4ce3d42c-1912-43be-82fb-428731ea0e4d`
- Project Root: `C:\Users\niko\Desktop\智能交易系统`
- Compaction Entry: `1e70c920`
- Tokens Before: 349200

## Session
- Session ID: 019fd662-ea0f-7f7b-801f-4ad3fae9205f
- Project Root: C:\Users\niko\Desktop\智能交易系统
- Current Objective: 方向门系列研究 — 验证市场状态适应策略（方向门 A/B → 变体矩阵 → 7.6 年全周期 → Optuna 调参），当前正在完成 Optuna 优化参数的最终回放验证
- Last Action: Optuna 优化完成（tf+nested 全局期 Sharpe 0.56→0.98），正在跑最优参数的最终回放验证（默认+nested / 优化+nested / 优化+sma / 优化+无门 四组对比）
- Current Mode: act（maestro session 驱动）

## Execution Plan
1. ✅ [方向门 A/B：mr 88 天 SMA200 门对比（maestro session `a-b-mr-88-sma200-20260807-101359`，已 seal）— `_DirectionGateWrapper` + `direction_gate` 参数，亏损 -83% 削减]
2. ✅ [方向门变体矩阵（sma/ema/slope(AA)/dual(AB)/nested(A大a小)）— GATE_BUILDERS 函数族 + `--gate-type`，固定窗口 88 天 A/B，单门 > 组合门]
3. ✅ [7.6 年全周期数据下载（66612 bars，2019-01→2026-08，零缺口）+ 全周期回放（mr -50.2% 负期望确认，tf+门 +18.7% 关键发现）+ 4 年窗口矩阵]
4. ✅ [Optuna 调参（scripts/optimize_tf_gate.py）：tf+nested 全局期 60 trials，Sharpe 0.56→0.98]
5. 🔄 [Optuna 最优参数最终回放验证（默认 vs 优化参数 × 门变体四组对比）— 进行中，命令已发出等待结果]
6. [待办：验证结果汇总 → 提交代码（paper_replay/optimize_tf_gate/scripts）+ 登记 roadmap + maestro session 收尾]

## Progress
### Done
- [x] 方向门 A/B（88 天）：baseline -2.62% vs SMA200 门 -0.63%（亏损 -76%、回撤 -58%）；修复 `_DirectionGateWrapper` 的 `required_regime` 被重置 bug；交付 `feat(strategy)` 提交 + 2 测试（全量 2058 passed）
- [x] 方向门变体矩阵（固定窗口 --end 2026-08-04, 2113 bars）：sma 最优 -0.63%、nested -0.80%、slope(AA) -1.03%（未超越单门）、dual(AB) -2.01%；交付 GATE_BUILDERS + `--gate-type` 5 变体 + 3 测试（全量 2060 passed，提交 3d39e85）
- [x] smart-search 研究：MTF 分层（HTF 门+LTF 入场）、过滤器滞后权衡（SMA/EMA/HMA）、"简单过滤器是更好生产基线"共识（证据存 C:\tmp\smart-search-evidence\20260807-gates\）
- [x] 10 年 BTC 样本下载：OKX BTC/USDT 1h 全量 **66612 bars**（2019-01-01→2026-08-07，每年 8760/8784 完整、0 缺口、0 NaN）— OKX 最早只到 2019，"10 年"实际 7.6 年
- [x] 全周期回放（66481 bars）：mr baseline **-50.2%**（模板负期望确认）/mr+sma -31.3%/mr+nested -26.1%；**tf baseline +3.6%（正期望）/tf+sma +18.7%（门放大 5 倍，Sharpe 0.13→0.51）** — 提交 docs(roadmap) 2c6858c
- [x] 4 年窗口矩阵（35065 bars）：mr 全负（best ema -13.8%）；tf best nested +7.54%（Sharpe 0.56）
- [x] 1 年窗口矩阵（8760 bars）：mr best nested -5.6%；tf best dual +0.67%
- [x] build_session 加 params 参数（向后兼容）+ scripts/optimize_tf_gate.py（生产回放路径 Optuna：每次 trial 走 TradingSession.on_bar + 门）
- [x] Optuna 优化（tf+nested，全周期 60 trials）：**best Sharpe 0.9806**，最优参数 fast_ma=24/slow_ma=49/atr_period=27/atr_multiplier=2.0/trailing_stop_atr_mult=4.3/stop_loss=0

### In Progress
- [ ] Optuna 最优参数最终回放验证：正在跑 4 组对比（默认+nested / 优化+nested / 优化+sma / 优化+无门）——命令已执行（timeout 1200s），输出大量 "Ignoring update for terminal order paper-X (was filled, got filled)" 日志（stderr 噪声，非错误），等待最终结果行（label: N单 +X% maxDD Y% Sharpe Z）

### Blocked
- 无

## Active Skills
- maestro（SKILL.md at C:\Users\niko\.pi\agent\npm\node_modules\pi-maestro-flow\.pi\skills\maestro\SKILL.md）— 已加载；session `a-b-mr-88-sma200-20260807-101359` 已 seal；无其他活动 Run
- smart-search-cli（C:\Users\niko\.agents\skills\smart-search-cli\SKILL.md）— 已使用（研究方向门/MTF/过滤器对比）；doctor ok
- todo 工具 — 激活中；#0-#26 全部 completed，无 pending 任务

## Goal State
- Current Goal: 方向门系列研究收官（当前无正式 goal 对象 — todo 驱动）
- Status: 进行中（Optuna 最终验证 → 提交收尾）
- Acceptance Criteria: 方向门全矩阵多窗口验证完成 + tf Optuna 调参 + 结果登记
- Verification State: 全量 2060 passed（提交 3d39e85 后）；当前无源码未提交改动（optima 脚本与 build_session params 已提交）

## Plan State
- Mode: act
- Status: empty（todo 驱动）
- Revision: 0
- Handoff: 无
- Reload Path: C:\Users\niko\.pi\workspaces\workspace-8f7ffd47\sessions\019fd662-ea0f-7f7b-801f-4ad3fae9205f-d2db2952\plans\current.md

## Todo State
### In Progress
- 无正式 todo 任务（#0-#26 全部 completed；当前 Optuna 验证非 todo 驱动）

### Pending
- [方向门研究收尾：Optuna 最优参数最终验证结果汇总 → 提交（若代码改动）+ roadmap 登记 + 汇报用户]

### Blocked
- 无

### Recently Completed
- [#21] P2.2-环境：torch 安装 + 真实推理冒烟（completed）
- [#22] P2.2-收尾：验证结果登记（completed）
- [#23-#26] M4-Phase1~4：基础设施加固/Per-Symbol/TOCTOU 锁/多 symbol 数据循环（全部 completed，代码已实现 + 登记）

## Working Files
- quantflow/strategy/research/paper_replay.py（修改中状态）：`build_session` 新增 `params: dict[str, Any] | None = None` 参数（传给 strategy_cls）；`replay` 新增 `direction_gate: bool | str`（False=关闭，字符串=GATE_BUILDERS 键名）+ `gate_sma_period`；`_DirectionGateWrapper` 改为接受 `allow: pd.Series` 布尔门 + 透传 required_regime；GATE_BUILDERS dict：`_sma_allow(200)`/`_ema_allow(55)`/`_slope_allow(200)`（AA 组合）/`_dual_ema_allow(20,50)`（AB 金叉）/`_nested_allow(4h,50)`（A大a小，前桶 shift 无 look-ahead）；`from typing import Any` 已加
- scripts/replay_paper_30d.py（已提交）：`--direction-gate`（store_true）+ `--gate-type`（sma/ema/slope/dual/nested，默认 sma）+ `--gate-sma-period`（默认 200）；`direction_gate=args.gate_type if args.direction_gate else False`
- scripts/optimize_tf_gate.py（已提交）：production-replay-path Optuna（PARAM_SPACE 6 参数、objective=Sharpe、批量 asyncio.run(_evaluate)、seed 42 TPESampler、best-params 复放验证）；`--gate/--trials/--days/--end`
- tests/unit/test_paper_replay.py（已提交）：7 测试（原有 5 + 方向门熊市抑制 + gate 变体构建/未知类型/默认 byte-for-byte）
- quantflow/strategy/sentiment.py（已提交）：`architecture=` 显式覆盖逃生舱（P2.2-C）
- scripts/evaluate_sentiment_models.py + scripts/domain_gold_crypto.json（已提交）：crypto 域评测 + neutral floor 校准
- scripts/verify_okx_throttler.py（已提交）：M4-6.4 真实 429 验证
- data/parquet/BTC_USDT/（新增数据）：66612 bars 7.6 年 1h（2019-01→2026-08，gitignore）
- .workflow/roadmap.md（已提交 M3-P2 段 7.6 年全周期研究登记，追加：mr -50.2% / tf+门 +18.7%）

## Reference Documents
- .workflow/roadmap.md（M1-M5 + M3-P2 权威源；P2.2 completed、M4 completed、M5 completed；M3-P2 Status 行已更新含 7.6 年全周期研究）
- spec:project:architecture-constraints-009（schema-only 防泄漏 arch 约束，M3-P0 look-ahead 约束在 nested gate 中引用）
- C:\tmp\smart-search-evidence\20260807-gates\（05 个证据文件：01-mtf.json / 02-filters.json / 03-exa-academic.json / 04-fetch-quantinsti.md / 05-search-filters.json）
- 之前会话：KNW-20260806-114636（spot-perp 验证）、KNW-20260806-145651（A2/C1）、KNW-20260807-151627（本会话 compact）

## Decisions
- **[方向门接入为 opt-in]**：`--direction-gate`/`direction_gate` 默认 False，显式 False 与旧路径逐字节一致（有测试）——不污染回测-实盘一致性契约，接入生产为独立决策
- **[简单单门 > 组合门]**：88 天固定窗口 slope(AA)/dual(AB) 未超越单 SMA——"不为叠加而叠加"（与外部研究"简单过滤器为更好生产基线"一致）
- **[nested 多周期方向]**：4h 门+1h 入场概念可行，大样本下优于单门（mr 全周期 -26.1% vs -31.3%；tf 4 年 best）——留作多周期实验方向
- **[窗口固定方法论]**：`--days` 随 now 漂移导致跨次对比失真 → 必须用 `--end` 固定窗口（发现 baseline 结果漂移 -1.04% vs -2.62%）
- **[mr 模板负期望确认]**：全周期 -50.2%（多窗口一致）→ 弃用或大改；tf+门为正期望（+18.7% 全周期）→ 优先优化方向
- **[Optuna 用生产回放路径]**：现有 quantflow optimize 用 generate_signals（无门/无 regime），不匹配——自建 optimize_tf_gate.py 走 TradingSession.on_bar

## Constraints & Preferences
- 不写无法验证的代码
- 全量测试覆盖后再提交；mypy/ruff clean 强制
- 提交中文描述
- pytest Windows 临时目录：`PYTHONUTF8=1 PYTEST_DEBUG_TEMPROOT=.pytest_tmp python -m pytest`
- config 优先级：命令行 > 环境变量 > YAML
- data/paper_replay/、data/parquet/、data/spot_perp_real/、data/live_evidence/、.pytest_tmp/、.pi/ 已 gitignore
- look-ahead 防泄漏（M3-P0）：nested gate 用前一根完整 4h bar（shift），不暴露未收盘 HTF 值
- API key 仅环境变量传递，不落盘（live 验证已遵循）

## Dependencies
- Runtime: Python 3.14.6（mise）、pytest 9.0.3
- 外部: OKX ccxt（网络，偶发瞬断需重试）、huggingface（下载已提速 3.5MB/s）
- 库: torch 2.13.0+cpu、transformers 5.14.1、pandas/numpy/duckdb/optuna/ruff/mypy、ccxt 4.5.56、ccxt.pro（watchOHLCV 可用）、Docker 29.6.2（Redis 容器可行）

## Changes Made
- 已提交（本会话后半）：feat(strategy) 方向门 A/B（3d39e85 前）、docs(roadmap) 7.6 年全周期研究（2c6858c）
- 待提交（Optuna 验证完成后）：无源码改动期待提交——optimize_tf_gate.py + build_session params 已在上一提交（3d39e85 的 feat(strategy) 包含）；若最终验证发现问题需修
- 数据资产（gitignore 不入库）：data/parquet/BTC_USDT/ 66612 bars、data/paper_replay/*.json（多窗口回放报告 ab_x/y1_x/y4_x/full_x/fx 系列）
- 后台任务：全部 completed/killed（无运行中）

## Critical Context
- **Optuna 最终验证命令已发出**（bash timeout 1200s，运行验证脚本）：对比 4 组 = 默认参数+nested门 / 优化参数+nested门 / 优化参数+sma门 / 优化参数+无门（BEST = {fast_ma:24, slow_ma:49, atr_period:27, atr_multiplier:2.0, trailing_stop_atr_mult:4.3, stop_loss_pct:0.0}）；预期输出格式 "label: N单 ±X.XX% maxDD Y.YY% Sharpe Z.ZZZ"；大量 "Ignoring update for terminal order paper-X" 日志为 stderr 噪声（paper gateway 终端单更新重入正常）非错误
- **优化前基准**：tf+nested 默认参数全周期 Sharpe 0.56 / 收益约 +7%（4 年窗口）；优化后 Sharpe 0.98（60 trials 全周期）
- **若最终验证通过**（优化参数延续或超越默认 nested 0.56）：登记 roadmap + 汇报用户 + 建议"接入生产决策点"（tf+门 已双窗口验证，生产接线为小改动）+ 下一可选项（多段 1 年切片诊断 2021/2022/2024）
- **若验证异常**（如订单 0 / NaN Sharpe）：先查 optimize_tf_gate.py 的 _evaluate（assert isinstance(sharpe,float) + NaN→-10 惩罚），再查 build_session params 传参是否生效（strategy_cls(params=params) 为 tf 的 __init__(params=None) 兼容）
- **未决研究结论供继续**：mr 模板负期望（弃用 or 大改）；方向门价值=策略质量筛（非仅熊市保护）；门变体最优跨窗口不稳定（无全窗口最优单门，nested 最稳健）

## Pending
1. 读取 Optuna 最终回放验证输出（4 组对比结果）
2. 若结果合理：登记 roadmap（Optuna 调参结果 tf+nested Sharpe 0.98）+ 汇报用户 + 给出接入生产/后续选项
3. 若代码有改动：全量测试（当前基线 2060 passed）+ ruff/mypy + 提交
4. 向用户报告：Optuna 优化结论 + 剩余决策点（tf+门接入生产 / mr 去留 / 多段 1 年切片诊断）

## Compaction Lineage
- Current Checkpoint: fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- Previous Checkpoint: 4ce3d42c-1912-43be-82fb-428731ea0e4d
- Inherited References: 全部 Working/Reference 文档（roadmap、schema_exposure、rd_agent、paper_replay、sentiment、spot_perp_sim、fetcher、store、validate 等 40+ 路径）
- Added References: scripts/optimize_tf_gate.py、scripts/verify_okx_throttler.py、scripts/domain_gold_crypto.json、scripts/evaluate_sentiment_models.py、scripts/finetune_fingpt.py（P2.2-C 与 M4-6.4 交付）
- Superseded References: quantflow/data/schema_exposure.py（已删，重复实现）

## Reference Lineage

- `.workflow/roadmap.md` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `.workflow/sessions/20260806-iss-20260804-003-spot-perp/runs/20260806-001-implement/report.md` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `C:\Users\niko\Desktop\智能交易系统\.workflow\knowhow\KNW-20260806-114636-session-compact-019fd662-ea0f-7f-3755d8ff-ee8b-45.md` — read, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `C:\Users\niko\Desktop\智能交易系统\.workflow\knowhow\KNW-20260806-145651-session-compact-019fd662-ea0f-7f-4ce3d42c-1912-43.md` — read, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `data/spot_perp_real/knowhow-okx-meta-endpoints.md` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `data/spot_perp_real/knowhow-spot-perp-validation.md` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/cli/main.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/common/schema_exposure.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `quantflow/config/strategies/spot_perp_arb.yaml` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/data/fetcher.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/data/market_meta_fetcher.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/data/schema_exposure.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `quantflow/data/store.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/execution/engine.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `quantflow/strategy/engine.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `quantflow/strategy/rd_agent.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `quantflow/strategy/research/backtest.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/strategy/research/paper_replay.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `quantflow/strategy/research/spot_perp_sim.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/strategy/sentiment.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `quantflow/strategy/templates/spot_perp_arb.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/strategy/validation/cpcv.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/strategy/validation/gate.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `quantflow/strategy/validation/wfo.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `scripts/benchmark_multi_symbol.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/build_spot_perp_dataset.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `scripts/domain_gold_crypto.json` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/download_spot_perp_data.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `scripts/evaluate_sentiment_models.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/finetune_fingpt.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/optimize_tf_gate.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/replay_paper_30d.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/replay_paper_f4f5.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `scripts/smoke_fingpt_generative.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/verify_okx_throttler.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `scripts/verify_s4_pipeline.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `scripts/verify_spot_perp_real.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `tests/integration/test_meta_backfill.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/integration/test_reconciliation_wiring.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/unit/test_exchange_health_wiring.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/unit/test_execution_engine_extra.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/unit/test_market_meta_fetcher.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `tests/unit/test_paper_replay.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/unit/test_reconciliation_engine.py` — read, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/unit/test_schema_exposure.py` — modified, active, 4ce3d42c-1912-43be-82fb-428731ea0e4d → 4ce3d42c-1912-43be-82fb-428731ea0e4d
- `tests/unit/test_sentiment.py` — modified, active, fe4c1f6a-2c98-4af1-a40d-5e9211e96229 → fe4c1f6a-2c98-4af1-a40d-5e9211e96229
- `tests/unit/test_spot_perp_arb.py` — read, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
- `tests/unit/test_spot_perp_sim.py` — modified, active, 3755d8ff-ee8b-4577-9fb1-56621c7c42eb → 3755d8ff-ee8b-4577-9fb1-56621c7c42eb
