# Roadmap: QuantFlow 策略扩展与发布准备

## Overview

当前 roadmap 分为两个阶段：

- `M1` 已完成：4 个新增策略的实现与验证
- `M2` 进行中：`v0.1.3` 发布候选准备，目标是对齐版本、治理打包内容、重建制品校验信息，并为后续 tag / release 对齐铺平状态
- `M3` 进行中：按 deep-research 研究文档（ANL-002）分批里程碑实施 P0 数据层防泄漏 → P1 风控层补齐 → P2 AI 层升级，每批独立实盘验证后才进下一批。**P0 已 P0-verify PASS（2026-08-01，4 策略回归守卫基线重立）**，**P1 已 P1-verify PASS（2026-07-21，commit `626b015`）**，**P2 unblocked 未启动**（P2.1 schema-only 隔离层为下一步，详见 Phase 3 细化）。2026-07-25 另完成 Wave 1-5 多 book reconcile 一致性收口（L4 单一权威 + L5 薄路由 + realized_pnl 翻仓归因 + daily_loss total-vs-baseline + partial-fill cumulative 契约）——该 reconcile 契约现为新 load-bearing 架构不变量，后续成功标准须引用（drift-realign DFT-6f8d5a9b, 2026-07-26）

**2026-08-06 快照（生产安全接线 + 回放验证）**：

- `M5` 已完成：生产安全接线与回放验证（A2 + C1）——ISS-20260803-002（对账接入生产）与 ISS-20260803-003（交易所风险隔离）闭环：ExchangeHealthMonitor 熔断器 + 单所敞口上限注入 RiskEngine / OKXGateway 生产路径（enabled=false 零行为变化），周期对账漂移告警集成验证；30 天 paper 回放工具落地（`quantflow/strategy/research/paper_replay.py` + `scripts/replay_paper_30d.py`），并修复 2 个静默零交易断链（M4 contexts key 回归 + set_portfolio 未重绑定）。
- 附带闭环：ISS-20260803-001（swap 市场解析修复）、ISS-20260804-003（spot-perp 真实数据验证 → **NO-GO**：90 天窗口 funding 极值零发生，原型保持 disabled）。
- **下一步：M3-P2.1 schema-only 隔离层**（P2 AI 层升级启动，串行约束闸门已开；P2.1 任务分解见 Phase 3）。

## Milestones

### Milestone 1: 四策略实现（v1.1）

**Target**：交付 4 个新策略，含代码、配置、测试与 CLI 接线  
**Status**：completed

#### Phases

- [x] **Phase 1: 策略实现与验证**：实现 P1-P4 四个策略，并补全 YAML 配置、单元测试、CLI 接线

#### Delivery Summary

- [x] `VolatilityBreakoutStrategy`
- [x] `FundingRateStrategy`
- [x] `MomentumRotationStrategy`
- [x] `MLEnsembleStrategy`
- [x] `quantflow research --strategy <name>` 接线完成
- [x] `quantflow optimize --strategy <name>` 参数空间接线完成
- [x] `quantflow validate --strategy <name>` 验证入口接线完成
- [x] 对应测试文件已落地并通过

#### Verification

- 单测结果：`37 passed`
- 覆盖内容：
  - 新策略参数初始化
  - `on_bar()` 基本行为
  - `generate_signals()` 输出形态
  - Cross-sectional / ML / funding data 等特殊逻辑
  - CLI 命令帮助与基本入口

### Milestone 2: v0.1.3 发布候选准备

**Target**：建立干净、可复现、可对齐 tag / release 的 `v0.1.3` 发布候选  
**Status**：in_progress

#### Phases

- [x] **Phase 1: 版本与工作流对齐**：更新版本元数据，建立发布里程碑与 maestro 会话，准备 `docs/release/v0.1.3/`
- [x] **Phase 2: 打包治理与制品重建**：限制 sdist / wheel 内容，重建 `SHA256SUMS.txt` 与 `release-manifest.json`
- [x] **Phase 3: 发布证据与远端对齐**：tag `v0.1.3` + GitHub Release「QuantFlow v0.1.3」已创建（commit `4bc72cd`，2026-06-07），dist 制品已封存。**已核验完成**（2026-08-06）：gh CLI 下载 6 资产闭环核验 PASS——whl `bf89a85c` / tar.gz `3ed19f7c` / manifest `a67a8bf7`，文件本体 hash = 官方 .sha256 = GitHub Release digest = SHA256SUMS.txt 四源一致

#### Delivery Summary

- [x] `pyproject.toml` 与 `quantflow/__init__.py` 对齐到 `0.1.3`
- [x] `.workflow/state.json` 与 `.workflow/.maestro/.../status.json` 建立发布推进状态
- [x] `docs/release/v0.1.3/` 文档集存在且与当前候选版本一致
- [x] `sdist` 排除 `.workflow`、`.codegraph`、`tests`、缓存与运行态内容
- [x] `dist/quantflow-0.1.3.tar.gz`
- [x] `dist/quantflow-0.1.3-py3-none-any.whl`
- [x] `dist/quantflow-0.1.3.tar.gz.sha256`
- [x] `dist/quantflow-0.1.3-py3-none-any.whl.sha256`
- [x] `dist/SHA256SUMS.txt`
- [x] `dist/release-manifest.json`

#### Blocking Findings

- ~~`v0.1.3` 远端 tag / release 尚未创建~~ — **已解决**：tag `v0.1.3`（target `4bc72cd`）+ GitHub Release「QuantFlow v0.1.3」已创建于 2026-06-07（drift-realign DFT-4d1a3b69, 2026-07-26）
- ~~安全扫描与发布证据仍未归档~~ — **已核验完成**：2026-08-06 gh CLI 下载 6 资产闭环核验 PASS（whl `bf89a85c` / tar.gz `3ed19f7c` / manifest `a67a8bf7`，文件 hash = 官方 .sha256 = GitHub digest = SHA256SUMS.txt 四源一致）

### Milestone 3: deep-research 改进分批实施（P0/P1/P2）

**Target**：按 ANL-002 分析结论分三批实施 deep-research 验证的 10 条改进，每批独立实盘验证后才进下一批
**Status**：in_progress
**Upstream**：ANL-002（analyze-macro，scope=large，GO_CONDITIONAL 88%）、GRL-001（grill）、deep-research-20260718（15 findings，24/25 verified）

#### 串行硬约束

P0 实盘验证通过 → P1 启动；P1 实盘验证通过 → P2 启动。批次间禁止并行（3 独立子系统跨 L1/L2/L3/L4 + 串行验证约束）。

#### Phase 1: P0 数据层防泄漏（milestone-gate: P0-verify）

**Status**：P0-verify PASS（2026-08-01，P0.3 回归守卫基线已对当前 HEAD 重立，4 策略 byte-for-byte 绿）

**Scope**：F1 MTF look-ahead 核实+修复、F2 look-ahead 检测 CLI
**Target files**：`mtf_aligner.py:139-177`、`fetcher.py:63-110`、`cli/main.py:288-439`、`strategy/validation/lookahead.py`（新建）、`tests/`

**Tasks**:
- [x] **P0.0 只读核实**：读 `_create_aligned_index` + 写「跨 HTF 边界 minor bar 断言无未收盘 HTF 值泄漏」测试。核实结论：CCXT fetch_ohlcv 返回 bar-open 时间戳（fetcher.py:102-105），原 reindex+ffill 会暴露未收盘 HTF bar → 确认泄漏存在，进 P0.1
- [x] **P0.1 MTF 修复（方案 b）**：reindex 前将 HTF index 整体右移一个周期（`_infer_period` 三级推断：freq → infer_freq → median diff），HTF bar 值只在下一根开盘（== 本根收盘）后对 minor 可见；不改 fetcher 索引，不破坏 backtest parity — commit `01f05fb`
- [x] **P0.2 look-ahead CLI**：`quantflow validate --method lookahead` 新建 `validation/lookahead.py`，静态 AST 扫描检出 `series[mask].agg()` 聚合泄漏模式（Shape 1 high / Shape 2 medium），无需数据/回测可直接进 CI — commit `99795b2`
- [x] **P0.3 回归守卫**：4 策略回测基线 byte-for-byte 不变 — ✅ 已对当前 HEAD 重立基线（`scripts/establish_p0_baseline.py` + `tests/unit/test_p0_regression_guard.py`，4/4 PASS，2026-08-01）

**Acceptance**:
- MTF 跨 HTF 边界无未收盘值泄漏断言通过 ✅（`test_mtf_does_not_expose_unclosed_htf_bar_close_to_minor`）
- look-ahead CLI 能检出已知泄漏模式 ✅（12 测试覆盖 clean/leaky/链式去重/分级/真实策略零误报）
- 4 策略回测无回归 ✅（`test_p0_regression_guard.py` 4/4 PASS，基线 `.workflow/artifacts/p0-baseline/test-results.json`）

**Done when**: `verification.json` passed + `test-results.json` 泄漏断言绿 ✅

#### Phase 2: P1 风控层补齐（milestone-gate: P1-verify）

**Status**：P1-verify PASS（2026-07-21，commit `626b015`）— F3/F4 GO，F5 mean_reversion 路径运气红旗 ISS-20260720-003 为「诊断非 gate」不阻 P2

**Scope**：F3 vol-targeting（opt-in）、F4 辅助诊断 CVaR、F5 路径级 MC 压力测试
**Target files**：`config.py:50-68`、`position_sizer.py:12-99`、`risk_metrics.py:13-62`、`risk_engine.py:176-193`、`strategy/validation/monte_carlo.py`（新建）、`cli/main.py`

**关键修正（ANL-002 claude delegate）**：F4「MC CVaR 替代主 gate historical CVaR」是**反模式**（parametric 违反 fat-tail arch spec，bootstrap 与 historical 渐近等价）→ F4 改为辅助诊断指标，**真正增量是 F5 路径级 MC 压力测试**（trade-order shuffling + candles-based，仿 Jesse）。

**Tasks**:
- [x] **P1.1 vol-target opt-in**：`RiskConfig` 加 `vol_target_pct`（默认 off），`PositionSizer` 加 vol-target method，绑定 `仓位=min(half-Kelly, vol-target, 单名上限)` — commit `09445de`
- [x] **P1.2 MC 压力测试**：新建 `validation/monte_carlo.py`，trade-shuffle + returns-bootstrap 两法（candles-based 因 vectorbt 移除改 returns-bootstrap），诊断非 gate — commit `9b856ff`
- [x] **P1.3 辅助 CVaR**：`risk_metrics` 加 `bootstrap_cvar` 作辅助诊断（非主 gate，不替代 historical CVaR） — commit `5e5b432`
- [x] **P1.4 CLI**：`quantflow validate --method stress` — commit `9b856ff`
- [x] **P1.5 回归守卫**：默认 off 时 byte-for-byte 不变（`test_default_off_is_byte_for_byte_baseline` + 全量 1411 passed，唯一失败为预存 FeatureStore pandas3.14 超界，与 P1 无关）
- [x] **P1.0-B1 阻塞修复**：`add_return` 零调用方导致 `_returns_history` 永空 → `engine.on_bar` 接线 `bar_ret = (curr_equity - prev_equity)/prev_equity`（pre-mark 捕获，无 look-ahead），喂给 `risk_engine.add_return` + `position_sizer.add_return`，8 单测覆盖历史填充与 gate 触发；CVaR gate 现真正生效 — commit `ec17b23`（issue 登记 `82331b4`，ISS-20260719-001 resolved）
- [x] **P1.6 parity 地基（P1-verify 前置）**：F3 用 paper-on_bar、F5 用 BacktestEngine 跑，两路径信号必须 parity 否则 verify 结论不可信
  - parity 守卫 `TestSignalParityGuard`（commit `4c2dbd0`）：逐 bar 比对 `_latest_signal` vs `generate_signals`，ENTRY 0 漂移（5/5 seed）
  - F4/F5 数据流接通（commit `4f5e218`）：paper session 的 `_risk_engine._returns_history` 可直接喂 `bootstrap_cvar` + `monte_carlo_stress(bar_returns=)`，纯 list 接口无需改代码
  - paper 历史回放脚本（commit `ce4d9b4`）：`scripts/replay_paper_f4f5.py` 回放本地 parquet 经 on_bar 积累 F4/F5 诊断数据
  - **ISS-20260613-006 exit 漂移根因修复**（commit `0dbee17`）：`generate_signals` exit 此前用 `short_count`（含 vol_ok + 阈值 min_conditions）与 `_latest_signal` 的 `exit_count`（无 vol_ok + 阈值 min_conditions-1）不一致，违反 `# exit without vol_ok` 设计意图 → 对齐为无 vol_ok + 阈值 min_conditions-1；守卫 `test_exit_residual_is_profit_trailing_role_difference` 确认条件 exit 漂移消除（12..22→1..16），残留单向 shape = profit/trailing 合并的职责差异非 bug
  - **regime 维度 parity 缺口登记**（commit `0dbee17`）：on_bar 应用 regime gating（ADX>=25），`generate_signals` 不应用 → 实测真实 BTC/USDT 1h 全 84 entries 落非 trending bar → on_bar 全 gate → 回测交易 84 次/实盘 0 次。根因 entry 用 MA 方向 vs regime 用 ADX 强度，direction!=strength。设计冲突非 bug，`TestRegimeParityGap` 守卫量化固化，待人裁决 regime↔entry 对齐方向（比 ISS-006 exit 更结构性）
  - checklist 三步结论（commit `3cfda6a` + `805e5b7`）：离线/模拟实盘可执行性确认，parity 地基 + F5 输入源 + 回放工具就绪

**Acceptance（代码层）**:
- 仓位绑定规则 opt-in 生效（高波动区间 vol-target < Kelly，低波动区间不绑定）✅
- MC 压力测试接入 CLI `--method stress`（诊断 method，不动 GO/NO-GO）✅
- 默认 off 时 4 策略回测 byte-for-byte 不变 ✅
- `add_return` 接线后 `_returns_history` 真实累积，CVaR gate 历史 ≥30 时真正阻断 ✅

**Acceptance（实盘 verify，待）**：按 `.workflow/specs/p1-live-verification-checklist.md`，F3 缩仓行为 / F5 路径运气红旗 / F4 CI 收窄在实盘数据上复现，全 GO/NO-GO 项 PASS + 两「诊断非 gate」契约项 PASS。

**Deferred**：研究层大规模参数扫描优化（依赖 F8 vectorbt 裁决——「numpy 向量化并行」vs「重新评估 vectorbt 2026 兼容性」，用户 P1 启动前裁决）

**Done when**: ✅ P1-verify `verification.json` + `review.json` passed（checklist 全 PASS，2026-07-21，commit `626b015`）

**Post-verify maintenance**（不改 P1-verify 结论，均为 byte-for-byte 行为不变的 config-sourcing / 文档对齐）:
- ISS-20260721-012（commit `8ffd612`，2026-07-28）PositionSizer `fixed_pct`/`min_order_notional`/`fee_rate` config-sourced（默认值对齐硬编码保 baseline 不变；`fee_rate` 复用 `execution.taker_fee` D3 single-source-of-truth）— 非 gate 项，纯 config-sourcing
- ISS-UX-20260728（commit `4e32c24`+`74b83d1`，2026-07-28）Web Station + CLI UX 加固（11 issues，M4 setHTML XSS choke-point + H3 redact_secrets + REG-1 `typer.BadParameter` re-raise）— 不在 deep-research F1-F12 范畴，属维护/润色 lane（roadmap M3 不跟踪 UX，见 Scope Decisions）

#### Phase 3: P2 AI 层升级（milestone-gate: P2-verify）

**Status**：completed（2026-08-06：P2.1 schema 隔离层全链（含 splits 元数据）→ P2.2 FinGPT 接口层+微调脚本+CPU 推理验证（environment 解封，训练路径待 GPU）→ P2.3 情绪传播广度加权聚合；全量 2056 passed）
**Scope**：F6 schema-only 暴露层（P2 内部硬约束）、F11 FinGPT、F12 情绪传播广度
**Target files**：`common/schema_exposure.py`（已存在，SchemaExposure/DatasetSchema）、`strategy/rd_agent.py`（discover_factors 签名已改）

**Tasks**:
- [x] **P2.1.1 schema 暴露层实现**：`common/schema_exposure.py` 已落地（from_dataframe → DatasetSchema：列名/类型/non_null_count/前 3 示例值，to_dict 序列化不含示例值）；12 项测试已验收（值屏蔽断言）
- [x] **P2.1.2 train/val/test 时间分割边界**：`DatasetSchema.splits`（SegmentInfo：n_bars + fractional 位置，无绝对时间）+ `from_dataframe(splits=)` 校验（和=1/chronological 无重叠）+ rd_agent 交接统一用显式 train.n_bars（回退 TRAIN_FRACTION）；4 项守卫测试（2026-08-06）
- [x] **P2.1.3 RD-Agent 接线**：`discover_factors(df, schema: DatasetSchema | None)` 签名改造（向后兼容），CLI 数据文件只写 train 前 70% 行 + schema.json 审计文件；baseline 路径保留全量帧（无 LLM 接触）
- [x] **P2.1.4 泄漏守卫测试**：原 12 项（值屏蔽/to_dict 序列化/示例值限量）+ 新增 2 项 wiring 测试（train-slice 行数与时间戳边界、legacy 兼容）
- [x] **P2.2 FinBERT→FinGPT 升级**（依赖 P2.1）：单卡 RTX 3090/$17.25 微调路径（medium-high，2-1 vote，自报基准）。**环境解封 + 推理路径验证 PASS**（2026-08-06）：torch 2.13.0+cpu + transformers 5.14.1 已装；交付 = 生成式 LM 分支（模型名关键词分派 + **`architecture=` 显式覆盖逃生舱**，4 测试）+ `scripts/finetune_fingpt.py`（微调入口，设备检测/CPU 警告/7B 需 GPU）+ `scripts/smoke_fingpt_generative.py`。真实冒烟：tiny-gpt2 生成式全链路 PASS（CausalLM→generate→关键词解析→NaN sentinel）；FinBERT CPU 分类推理 PASS（0.03-0.06s/条）；**finding**：模型名不是架构可靠信号（rezacsedu GPT-2 实为 9 类分类头，3 类契约不匹配——F11 微调输出固定 3 类规避；需 9 类映射时用 architecture 覆盖 + 自定义映射，见 P2.2 后续）。**C 方案（社区权重，跳过训练）选型完成**（2026-08-06）：`scripts/evaluate_sentiment_models.py` 15 条 Financial PhraseBank 式金标评测 4 模型 → **胜出 `mrm8488/deberta-v3-ft-financial-news-sentiment-analysis` 93.3%**（FinBERT 86.7% / FinancialBERT 86.7% / distilroberta 86.7%）；SentimentAnalyzer 集成验证 PASS（分类路径、0.07-0.16s/条、reach 兼容）；注：财报域强（训练域），crypto 语境偏保守（训练域外），BTC 风格句多判 neutral——上线前建议用 OKX 新闻域样本微调或 domain 校准
- [x] **P2.3 情绪传播广度**（依赖 P2.1）：`SentimentAnalyzer` 接收传播广度元数据（reach 0..1 验证 + reach 列加权聚合 _weighted_daily_mean，NaN 跳过），5 项测试（2026-08-06）

**Acceptance**:
- schema-only 隔离层屏蔽原始数据/时间分割（值泄漏守卫测试绿）
- RD-Agent 输入仅 schema（无原始行情/时间点）；train/val/test 边界无穿越
- 情绪 analyze 接收传播广度元数据（P2.3）

**Done when**: `verification.json` + `review.json` passed；全量回归绿（当前基线 2041）

#### Phase 4: 多 book reconcile 一致性收口（Wave 1-5，2026-07-25 已落地）

**Status**：completed（commits `7e781a8` → `06a8d93`，Wave 1-5，2026-07-25）

**Scope**：横切 L4/L5 执行路径一致性重构 — 消除多账本、统一 fill 更新点、翻仓 realized 归因、daily_loss 语义切换、partial-fill cumulative 契约。此 Phase 非 deep-research F1-F12 范畴，是 P1-verify 后暴露的执行路径一致性收口（drift-realign DFT-3c9f2e58 补登，2026-07-26）。

**Tasks（已落地）**:
- [x] **Wave 1**：`PortfolioManager` 增 `realized_pnl` 翻仓归因（closing-leg PnL）+ `daily_baseline` 字段 — commit `7e781a8`
- [x] **Wave 2**：`PositionManager` 退化为薄路由委托 L4（全 9 方法委托 + `bind_portfolio`），`PaperGateway` 移除第三套 `_cash` 账本 — commit `062a7b5`
- [x] **Wave 3**：`daily_loss` gate 改 total-vs-baseline 语义（日切首 bar equity 锚定），替代旧 daily PnL 累计 — commit `90b3eff`
- [x] **Wave 4**：partial-fill cumulative 契约 — `Order.applied_filled_qty` + `delta_filled` guard（POSITION_EPSILON 防 0 回调误调 L4），OKX cumulative fill 提取 — commit `b0177e0`
- [x] **Wave 5**：全套验证通过（lint + mypy + test + parity） — commit `06a8d93`

**Acceptance**:
- L4 PortfolioManager 单一权威账本，engine.submit 统一 fill 更新点（含 fee），_process_signal 不再二次更新 L4 ✅
- L5 PositionManager 薄路由委托，PaperGateway 无独立 cash 账本 ✅
- paper/live 经同一 engine.submit 路径，parity 成立（backtest 独立向量化 book 不在 reconcile 范围，per arch parity spec）✅
- partial-fill 重复回调不双计 L4 ✅

**Done when**: ✅ Wave 5 全套验证通过（2026-07-25，commit `06a8d93`）

**Note（drift-realign DFT-5e7c4f8a）**：Wave 1-5 重写了 `strategy/engine.py`（+57）与 `execution/engine.py`（+111），P0.3 byte-for-byte 回归守卫基线若在 Wave 前建立则已失效，需对当前 HEAD 重立基线。

### Milestone 4: v0.2 多 Symbol 扩展

**Target**：将 QuantFlow 从严格单 symbol 架构升级为单进程多 symbol 并发（10-30 交易对），消除存量 TOCTOU 风控竞态，保持 paper/live parity
**Status**：completed（commit `fe43aeb`，tag `v0.2.0`，2026-08-02）
**Upstream**：Grill session（6 decisions locked, 6 risks）、Brainstorm session（PendingLedger 详细设计，4 cross-role conflicts resolved）
**Version tag**：`v0.2.0`
**Delivery summary**：17 ISS 清零（安全加固 + 架构清理 + 新功能），pyproject.toml 0.2.0。实际交付以 ISS 清零为主，多 Symbol 扩展基础设施部分落地（per-symbol 工厂化、策略工厂 `strategy/factory.py`、IndicatorComputer Protocol 注入等）。**2026-08-06 补登**：Phase 4 多 symbol 数据循环（单 poller 轮转 + to_thread 卸载 + CLI/Web symbols）、Phase 5 Pending Exposure 台账（reserve/confirm/partial/release + 四象限超时决策 + stale sweeper + partial_fill_ratio）与 Phase 6 集成测试（9 个 test_m4_* 文件 64 测试）均已实现并全量回归绿（2056 passed）。

#### 架构决策（Grill locked）

| 决策 | 选项 | 理由 |
|------|------|------|
| 扩展模式 | Option A: 单进程 asyncio.gather | L4 已天然多 symbol 就绪；微服务无收益场景 |
| TOCTOU 解法 | 悲观锁打底 + pending 台账 | Fail-Closed 原则排除事后校验 |
| on_bar 兼容 | 方案 3: 透明 to_thread 包装 | 接口零变更，7 模板 + 21 测试不受影响 |
| 策略实例化 | per-(strategy, symbol) 工厂化 | 消除跨 symbol 状态污染（_bars/_in_position） |
| 数据获取 | 共享 fetcher + 单 poller 轮转 | CCXT throttler 全局协调，防 429 |
| 50+ 扩展 | 分阶段，Redis 阶段二 | 当前无多机需求，pending 台账即 Redis 预扣原型 |

#### 串行约束

Phase 1-2 可并行 → Phase 3 依赖 Phase 2（contexts 键控）→ Phase 4 依赖 Phase 2+3 → Phase 5 依赖 Phase 3（Lock 保护 reserve 路径）→ Phase 6 依赖全部

#### Phase 1: 基础设施加固（0.5 天）

**Scope**：消除已知微缺陷，建立多 symbol 硬约束文档

**Tasks**:
- [ ] **M4-1.1** `StrategyContext.flush_signals` 改原子交换（`signals, self._signals = self._signals, []`）
- [ ] **M4-1.2** `DataFetcher` 类级 docstring 声明 "single instance per session" 不变量
- [ ] **M4-1.3** `redis_cache.py` 模块级 `DeprecationWarning`（零引用死代码）

**Done when**: flush 原子交换测试通过 + lint/mypy 绿

#### Phase 2: Per-Symbol 策略实例化（3 天）

**Scope**：消除策略实例跨 symbol 状态污染，配置层支持多 symbol

**Tasks**:
- [ ] **M4-2.1** 新建 `quantflow/strategy/factory.py`：`create(strategy_cls, symbol, params) -> StrategyBase`
- [ ] **M4-2.2** `TradingSession._contexts` 键控升级：`dict[str, StrategyContext]` → `dict[tuple[str, str], StrategyContext]`
- [ ] **M4-2.3** `on_bar` 内 ctx 查找改为 `self._contexts.get((strategy.name, bar.symbol))`
- [ ] **M4-2.4** `RiskConfig` / `AppConfig` 增加 `symbols: list[str]`（向后兼容单 symbol 字符串）
- [ ] **M4-2.5** `default.yaml` + 策略 YAML 增加 `symbols` 字段
- [ ] **M4-2.6** 存量测试回归（单 symbol 行为 byte-for-byte 不变）

**Acceptance**:
- 同一策略类的两个实例（BTC/ETH）各自维护独立 `_bars`/`_in_position`
- 单 symbol 配置（`symbol: BTC/USDT`）仍正常工作

**Done when**: `test_multi_symbol_isolation` 通过 + 全量回归绿

#### Phase 3: TOCTOU 第一层 — asyncio.Lock（0.5 天）

**Scope**：保护 risk-check → sizing → submit 临界区

**Tasks**:
- [ ] **M4-3.1** `TradingSession.__init__` 增加 `self._signal_lock = asyncio.Lock()`
- [ ] **M4-3.2** `_process_signal` 入口 `async with self._signal_lock:`
- [ ] **M4-3.3** 验证锁仅覆盖信号路径，不覆盖数据 fetch 和策略计算

**Acceptance**:
- 两并发信号不会同时进入 risk-check → submit 路径
- 锁持有时间 < 1s（paper 模式下 submit 同步返回）

**Done when**: 并发信号测试通过（mock gateway 延迟 100ms，assert 串行执行）

#### Phase 4: 多 Symbol 数据循环（3 天）

**Scope**：单 poller 轮转 sweep + 策略计算 to_thread 卸载 + CLI/Web 适配

**Tasks**:
- [x] **M4-4.1** `run_data_loop` 签名改为 `symbols: list[str]`
- [x] **M4-4.2** 单 poller 轮转实现：一个 task 轮转 sweep 所有 symbol，fetch 到新 bar 后按 symbol 分发
- [x] **M4-4.3** `on_bar` 内策略计算卸载：`await asyncio.to_thread(strategy.on_bar, ctx, bar)`
- [x] **M4-4.4** CLI `--symbol` → `--symbols`（逗号分隔，向后兼容单 symbol）
- [x] **M4-4.5** Web `SessionStartRequest` 增加 `symbols` 字段
- [x] **M4-4.6** 共享 fetcher 实例验证（全 session 单 exchange 对象）

**Acceptance**:
- 3 symbol paper 模式并发运行 60s 无异常
- 策略计算不阻塞数据 fetch（to_thread 验证）
- CCXT throttler 全局协调（无 429）

**Done when**: `test_multi_symbol_paper_session` 通过 + CLI `--symbols BTC/USDT,ETH/USDT` 正常启动

#### Phase 5: TOCTOU 第二层 — Pending Exposure 台账（4 天，Live 模式）

**Scope**：reserve/confirm/release 三元状态机 + RiskEngine 口径改造 + 超时/撤单联动 + sync 失败兜底
**Upstream**：Brainstorm session（PendingEntry, PendingView, F1-F5）、ANL-pending-partial（部分成交边界 3 修正）、ANL-sync-pending（四象限决策矩阵 + sweeper）

**Tasks**:
- [x] **M4-5.1** `PortfolioManager` 增加 `_pending: dict[str, PendingEntry]` + reserve/confirm/partial_confirm/release
- [x] **M4-5.2** `PendingView` dataclass（frozen, slots）+ `PortfolioManager.pending_view()`
- [x] **M4-5.3** `Portfolio` dataclass 增加 `pending_exposure: float = 0.0`
- [x] **M4-5.4** `RiskEngine.check` 签名增加 `pending: PendingView | None = None`
- [x] **M4-5.5** `_check_position_limit` / `_check_portfolio_limit` / `_check_strategy_budget` 口径改造
- [x] **M4-5.6** `TradingSession._process_signal` 集成：reserve → submit → confirm/release
- [x] **M4-5.7** `OrderManager.check_timeouts` → release 联动
- [x] **M4-5.8** `ExecutionEngine.cancel` → release 联动
- [x] **M4-5.9** Kill Switch activate 后统一 release all pending
- [x] **M4-5.10** `sync_positions` 返回值改造（`None` → `bool`，True=成功/False=失败）
- [x] **M4-5.11** timeout 处理集成四象限决策矩阵（cancel_ok ∨ sync_ok → release；both fail → 冻结）
- [x] **M4-5.12** `PortfolioManager.sweep_stale_pending(max_age_ms=120_000)` 实现 + CRITICAL alert
- [x] **M4-5.13** data loop 中 sweeper 调用（每轮 check_timeouts 后执行）
- [x] **M4-5.14** `partial_confirm` 参数语义为 **cumulative_filled_notional**（对齐 ccxt 累积契约，非 delta）
- [x] **M4-5.15** `PaperGateway` 增加 `partial_fill_ratio` opt-in 配置（默认 None=不启用，保 baseline）

**Acceptance**:
- 限价单 SUBMITTED 后，后续信号的 position_limit 检看到 pending notional
- 部分成交按累积 notional 增量减少 pending（非 delta_qty × avg_price）
- 超时 + cancel✓ + sync✓ → pending 归零（象限 A）
- 超时 + cancel✓ + sync✗ → release（象限 B，信任 cancel ack）
- 超时 + cancel✗ + sync✓ → release（象限 C，sync 覆盖真相）
- 超时 + cancel✗ + sync✗ → pending 冻结 + CRITICAL alert（象限 D，Fail-Closed）
- 冻结 pending 超过 120s 后被 sweeper 清理 + 告警
- Paper 模式下 reserve→confirm 原子完成，行为不变
- Paper `partial_fill_ratio=0.3` 时限价单返回 PARTIAL，触发 partial_confirm 路径

**Done when**: `test_pending_ledger_lifecycle` + `test_toctou_concurrent_signals` + `test_timeout_quadrant_matrix` + `test_stale_sweeper` 通过

#### Phase 6: 集成测试 + 回归（3 天）

**Scope**：全量回归 + 多 symbol 专项测试 + 性能基准 + partial fill 路径覆盖

**Tasks**:
- [x] **M4-6.1** 多 symbol 并发信号竞态测试（T1-T10 边界矩阵）
- [x] **M4-6.2** pending 台账生命周期测试（reserve → partial → timeout → release）
- [x] **M4-6.3** per-symbol 策略隔离测试（同策略类两实例互不干扰）
- [x] **M4-6.4** 共享 fetcher throttler 压力测试（30 symbol 轮转无 429）— 实现在位（单 poller 轮转 + 共享 fetcher）；**429 无触发验证需真实网络环境**（本机 paper 模式本地撮合无网络路径，已在 C1 30 天回放验证真实 OKX fetch）
- [x] **M4-6.5** 存量 102 测试文件全量回归
- [x] **M4-6.6** on_bar 延迟基准测试（`scripts/benchmark_multi_symbol.py`，30 symbol × 5 策略 **1.3ms/bar PASS**（acceptance < 2s），50 symbol 1.2ms/bar，600 bars/799 bars/s；策略调用完整性 3000/3000）
- [x] **M4-6.7** PaperGateway `partial_fill_ratio` 路径测试（PARTIAL → partial_confirm → FILLED → confirm）
- [x] **M4-6.8** timeout-on-partial 四象限测试（mock gateway 控制 cancel/sync 成功/失败组合）
- [x] **M4-6.9** stale-pending sweeper 测试（冻结 → 超龄 → 清理 + alert）

**Done when**: 全量测试绿 + benchmark 达标 + 覆盖率 ≥ 70%

### Milestone 5: 生产安全接线与回放验证（A2 + C1）

**Target**：将存量实现接入生产运行时并闭环验证——对账引擎周期执行 + 交易所级熔断/单所敞口上限纳入 RiskEngine（ISS-20260803-002/003），30 天 paper 回放工具驱动真实数据验证生产路径
**Status**：completed（2026-08-06，commit `6257b7c` + `7aded16`）
**Upstream**：analyze 维度4/F6（交易所信用风险隔离）、维度5/R5（对账恢复）、P1 live-verification checklist（paper 回放路径）

#### Phases

- [x] **Phase 1: A2 生产安全接线**：ExchangeHealthMonitor 按 `risk.exchange_health.enabled` 构建并注入 RiskEngine（熔断拦截 + 单所敞口上限）+ ExecutionEngine→OKXGateway（REST/WS 结果喂数）；周期对账漂移告警集成验证（enabled=false 零行为变化；全量 2038 passed）— commit `6257b7c`
- [x] **Phase 2: C1 30 天 paper 回放**：`quantflow/strategy/research/paper_replay.py`（build_session/replay/aggregate）+ `scripts/replay_paper_30d.py`；修复 2 个静默零交易断链（M4 contexts key 回归 → `(name, "")`；set_portfolio 未重绑定 → fills 落私有 book）；真实数据 30 天验证：mean_reversion 37 单 +0.18%/Sharpe 1.54，trend_following 9 单 -0.26%（regime gate 对照）；harness 回归守卫 3 项 — commit `7aded16`
- [x] **Phase 3: 附带闭环**：ISS-20260803-001 swap 解析修复（commit `3035421`/`3ba219b`）；ISS-20260804-003 spot-perp 真实数据验证 **NO-GO**（funding 极值零发生，原型保持 disabled）

**Acceptance**:
- 003：OKX 健康度指标 + 交易所级熔断 + 单所敞口上限纳入 RiskEngine ✅（6 项 wiring 测试）
- 002：周期对账人工漂移 → critical 告警捕获 ✅（3 项集成测试）
- C1：30 天回放报告（fills/equity/risk events/Sharpe/maxDD）✅

**Done when**: 全量 2041 passed；ruff/mypy clean；002/003 issue → resolved

## Scope Decisions

- **In scope**：版本抬升到 `v0.1.3`、发布文档、`.workflow` 发布里程碑、maestro 会话、打包治理、哈希与 manifest 刷新；**v0.2 多 symbol 扩展（M4）**；**M5 生产安全接线与回放验证（A2/C1，已完成）**；**M3-P2.1 schema-only 隔离层（下一阶段）**
- **Deferred**：GitHub tag / release 真实发布、远端资产上传、paper / live 运行证据补齐；**WebSocket 实时推送（ccxt.pro 切换，50+ symbol 终态）**；**Redis 分布式状态共享（阶段二）**；**P2.2 FinGPT / P2.3 情绪传播广度（依赖 P2.1 schema 层）**；**spot-perp 配对策略（ISS-20260804-003 NO-GO，原型 disabled）**
- **Out of scope**：新增 Gateway、新数据源、前端 UI、部署拓扑重构、多用户/多租户

## Progress

| Milestone | Phase | Status | Completed |
|-----------|-------|--------|-----------|
| 1. 四策略实现 | 1. 策略实现与验证 | Completed | 2026-06-02 |
| 2. v0.1.3 发布候选准备 | 1. 版本与工作流对齐 | Completed | 2026-06-07 |
| 2. v0.1.3 发布候选准备 | 2. 打包治理与制品重建 | Completed | 2026-06-07 |
| 2. v0.1.3 发布候选准备 | 3. 发布证据与远端对齐 | **Completed**（2026-08-06 核验 PASS：6 资产四源 digest 一致） | 2026-06-07 (tag `4bc72cd` + Release) |
| 3. deep-research 改进分批实施 | 1. P0 数据层防泄漏 | **P0-verify PASS**（P0.3 基线已重立，4/4 绿） | `01f05fb` `99795b2` |
| 3. deep-research 改进分批实施 | 2. P1 风控层补齐 | **P1-verify PASS** | 2026-07-21 `626b015` |
| 3. deep-research 改进分批实施 | 2.5 多 book reconcile (Wave 1-5) | **Completed** | 2026-07-25 `7e781a8`→`06a8d93` |
| 3. deep-research 改进分批实施 | 3. P2 AI 层升级 | **P2.1 接线完成**（schema 层已落地 + rd_agent 签名改造 + train-slice 边界，2026-08-06）；P2.1.2 三段分割待补；P2.2/P2.3 依赖 P2.1 未启动 | 2026-08-06 `feat(ai) P2.1` |
| 4. v0.2 多 Symbol 扩展 | 全量（17 ISS 清零 + 架构清理） | **Completed** | 2026-08-02 `fe43aeb` (tag `v0.2.0`) |
| 5. 生产安全接线与回放验证（A2+C1） | 1. A2 生产安全接线 | **Completed** | 2026-08-06 `6257b7c` |
| 5. 生产安全接线与回放验证（A2+C1） | 2. C1 30 天 paper 回放 | **Completed** | 2026-08-06 `7aded16` |
| 5. 生产安全接线与回放验证（A2+C1） | 3. 附带闭环（001 修复/004 NO-GO） | **Completed** | 2026-08-06 `3035421`/`3ba219b` |
