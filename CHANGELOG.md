# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

## [0.11.0] — 2026-08-23

### Security
- **限频键伪造绕过（HIGH，SEC-REV020）**：`X-Forwarded-For` 不再被无条件采信为限频桶键——仅当直连 peer 位于 `STATION_TRUSTED_PROXIES` 白名单时生效；桶键折叠 Bearer 凭据 SHA-256 摘要（按凭据分桶替代共享 per-IP 桶）、陈旧桶惰性驱逐、尾斜杠规范化封堵 `/download/` 变体；新增不变量测试保证所有 mutation 路由均在限流名单内
- **同源策略收紧（SEC-REV020）**：未配置 token 时，非回环来源且缺失 Origin 头的变更请求一律 403；持有效 token 时 Origin 缺失放行（Bearer 已证明非浏览器意图），跨域携带 token 仍 403
- **响应安全头强化（REV-010 + SEC-REV020）**：全部响应携带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、CSP（`frame-ancestors 'none'` + 显式 `script-src/style-src 'self'` + `object-src 'none'` + Permissions-Policy）、`Referrer-Policy: no-referrer`；未知 API 404 不再回显请求路径
- **对账审计签名密钥外置（SEC-REV020）**：移除硬编码 `"test-only-reconciliation"` HMAC 密钥，改读 `QUANTFLOW_AUDIT_HMAC_KEY` 环境变量；未配置时降级为「不签名 + 明确警告」
- **配置样例防凭证泄漏（SEC-REV020）**：`default.yaml` 移除 `${TELEGRAM_BOT_TOKEN}` 插值示例——加载器从不展开环境变量，该示例诱导将真实 token 提交进受跟踪 YAML
- **web 入口安全基线（REV-010）**：run_station 前置 structlog 脱敏链；`--mode okx` 遗留别名并入 Kill-Switch 强制启用门；reconciliation 异常日志与 redis 连接串脱敏（密码不再入日志）；`SessionStartRequest.symbol` 过 web 边界符号校验；rdagent 子进程改白名单环境变量
- **错误码语义修正（SEC-REV020）**：未知策略 id 由 KeyError→500 归一为 ValueError→400（research/validate 双入口）

### Fixed
- **回撤符号契约（Critical，REV-025）**：后端恒定输出 drawdown ≤ 0，前端 `drawdown > 0.05` 危险分级为死代码——会话面板改按 `Math.abs(drawdown)` 阈值分级、执行面板回撤红色高亮与百分号修正、overview max_drawdown 阈值比较修正（原逻辑恒绿）
- **净值指标恒绿（REV-022）**：权益指标原「equity > 0 即绿色」（即使 -50% 回撤也绿）——改为对照初始资本的 go/warn/danger 分级；执行面板按未实现盈亏符号着色
- **实盘确认双因子（REV-022）**：LiveModeConfirmDialog 由「勾选确认 **或** 口令任一即解锁」改为两者同时满足
- **告警静默失效（REV-024）**：文档记载的 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 环境变量此前从未到达 AlertManager——sink 启动时回落读取环境变量装配（含 3 个回归测试）
- **CLI 读不到自己的下载数据（HIGH，REV-024）**：research/optimize/validate 按裸 symbol 查询而 download 默认写 `-OKX` 分区——三命令统一接入 `store.resolve_symbol`
- **web validate 忽略时间窗（REV-024）**：start/end 参数此前被丢弃（恒回全历史）——字段接入 `_query_symbol_frame`
- **Bybit 线性永续下载路径损坏（REV-013）**：`bybit_market_id` 将全部 `BTC/USDT:USDT` 永续误入交割合约解析分支而报错——永续改按现货方式映射共享原生 id；附带 `_normalize_epoch_ms` numpy 输入崩溃加固
- **管理台冷启动雪崩（REV-021/025）**：并发冷请求各自触发全量 parquet 扫描（实测 ~1.6–2.3s × N）——TTLCache single-flight 合并 + 重算迁出存储锁（一次扫描服务全部请求且不再阻塞普通读写）；`/api/strategies` ~340ms → ~2ms
- **数据面板全局刷新失效（REV-012）**：三方 queryKey 各自漂移致 data 面板任何全局路径都无法刷新——收敛为单一映射表；后台标签页停止轮询
- **持仓/订单字段漂移渲染 NaN%（UI2-REV014）**：前端接口与后端 payload 漂移（`return_pct/type` vs `pnl_pct/order_type`）导致 PnL 显示 NaN%、订单类型徽章空白——已对齐
- **可靠性批次（DEF-REV011）**：OKX 网关瞬断后以匿名凭据进入重连循环；emergency 级风控事件真正拉起 Kill Switch；optimize/validate 失败退出码 0→1；interval=0 忙轮询钳制；trades/feature store 写入并入统一分区锁协议
- **multi_tf 资源治理（REV-017/019）**：每 symbol DuckDB 连接泄漏（try/finally 包裹）；50-symbol 无界扇出钳制到 8 并发；event_bus 派发期间订阅变更 RuntimeError（迭代快照化）

### Changed
- **无障碍加固（REV-022，WCAG 映射）**：约 22 个表单字段 label 编程关联；策略卡键盘可操作；失败 `role=alert`、成功 `role=status` 播报；面板切换焦点迁移 + skip-to-content；数据表 `th scope="col"`
- **枚举展示中文化收敛（REV-022/025）**：`lib/labels.ts` 统一六类枚举映射，原始枚举不再漏出中文界面；补齐后端实际值 `demo-ready`
- **操作反馈统一（REV-023/026）**：`useMutationFeedback` 单钩子契约——即时 toast + 可追溯内联提示 8 秒自清（错误驻留）；六个 mutation 面 DOM 契约一致
- **可复制 ID 与格式层（REV-023/026）**：CopyableText 应用于 session_id/订单号/config_path/存储路径；`lib/format.ts` 统一日期/金额/百分比格式
- **配置面修复（REV-024）**：`.env.example` 对照穷尽式审计重写（删 6 幽灵变量、补 compose 必填与安全变量、文档化覆盖语法）；活跃风控参数 `risk.cvar_limit` 补入 default.yaml；`status` 策略列表改读活目录
- **日志降噪（REV-024/025）**：约 330 调用点审计后的低风险批次——例行 info→debug、重叠错误合并、自愈连接失败降级、session 崩溃补日志并防刷屏
- **前端测试基建从 0 到 1（REV-026）**：vitest@4 + Testing Library + jsdom（`npm test`），首批 7 个组件/hook 测试；共享 FakeDataStore + Protocol 收集期契约测试
- **结构工程（REV-013/014，行为不变）**：OKX/Bybit 分页循环去重；四个 meta 回补命令骨架合一；monitoring_snapshot 三段拆分


### Features
- **多时间框架并行分析（PERF-REV015）**：`data/resample.py` 本地重采样层——仅下载 {5m, 1d} 基础网格即可派生全部 24 档周期（5m…30d，含交易所不原生支持的 45m/7h/16h/32h）；UTC floor 锚定 + leak-safe 尾桶丢弃 + 幂等性测试
- **新端点 `POST /api/analysis/multi-tf`**：每 symbol 单次 base 读取 → 内存重采样全部请求周期；部分成功语义；已接入限流白名单
- **overview TTL 缓存**：data/monitoring/execution 三快照共用一次 parquet 全扫（原每轮询周期重复 2-3 次），命中返回深拷贝
- **行情图表面板（UI-REV016）**：lightweight-charts v4 蜡烛图 + 成交量副图，24 周期切换（分段+分组弹层），symbol/TF/成交量开关持久化，主题翻转自动重配色

### Fixed
- multi-tf 端点 start/end 参数透传缺失（fields=full 返回全历史）；ISO 日期→epoch-ms 归一化
- `_analyze_symbol` DuckDB 连接泄漏（每 symbol 一条未关闭）
- 重采样单 base bar 尾桶泄漏（1 根 bar 冒充完整大周期 K 线）+ 回归测试
- 图表双重 ms→s 时间换算（渲染必崩，上线前拦截）；主题切换后成交量柱颜色滞留
- 验证门禁 NO-GO 结果误渲染为绿色徽章（"no-go".includes("go") 判断顺序反转）
- session 停止零确认（紧邻刷新按钮，误触即终止会话）；数值表单 NaN/清空静默归零

## [0.10.0] — 2026-08-22

### Features
- **web station 异步化**：全部同步 handler 经 `asyncio.to_thread` 下放（含 download 落盘段与 monitoring/execution 快照），kill-switch/session 控制面不再被 parquet 扫描阻塞；overview 单次聚合 SQL 替代每符号双全史扫描（约 2x）
- **下载并发骨架**：OKX `download --concurrency N`（默认 1 零行为变化，>1 待限频门禁验证）；`DataFetcher.fetch_ohlcv_multi` 与 Bybit 对齐
- **CLI 冷启动优化**：策略目录懒加载导入，1.90s → 0.59s

### Fixed
- **并发写丢行**（ISS-REV007-01）：分区写改为 per-partition 线程锁 + 跨进程 FileLock + tmp 原子替换；tag_data_source 与 save 共用同一锁协议
- **resolver 补齐**：`-BYBIT` 入链；多候选时按后缀优先级决策并告警共存（回退 RV-010 earliest-start 方案——其会永久遮蔽干净分区）
- **分页硬顶 fail-loud**：OKX/Bybit K线、funding/mark/OI 分页达上限改抛 `DataError`（不再静默截断入库）
- **裸 query 收口**：rdagent/ml-train 等 4 处接入 resolver；空目录/坏分区不再使 overview 500（probe + fallback 保护 + COALESCE unknown）
- **archive 迁移工具修复**：候选分区按规范化存储名探测（原斜杠路径永不命中致 `--apply` 永久 BLOCKED）；补 `-BYBIT` 候选
- **私有符号解耦**（ISS-REV007-05）：重试/限频原语上收 `quantflow/common/netretry.py`

### Engineering
- **结构拆分第一批**：`cli/render.py`（12 渲染辅助）、`common/netretry.py`、`indicators compute_all` 表驱动化（21 重 if → 声明式 spec 表）、`data/store.store_scope` 生命周期上下文管理器（幂等 close）
- **安全网先行**：CLI 20 命令注册顺序 golden + validate 契约测试冻结，为 commands/ 分包铺路
- **三模型共识审查两轮**（REV-008 性能改动对抗审查 / REV-009 结构设计），TOP 缺陷全部闭环

## [0.9.0] — 2026-08-21

### Features
- **多交易所历史数据接入**：Binance 公共归档（`download-binance`，月度 CSV 免鉴权）+ Bybit V5（`download-bybit`，CCXT，spot/linear/inverse 含交割合约）
- **OKX 多标的批量**：`download --symbols BTC/USDT,ETH/USDT,SOL/USDT`（共享单实例串行限速 + 逐 symbol 失败隔离，M4-1.2 不变量）
- **元数据扩展**：Bybit funding/OI 历史（`download-bybit-funding/-oi`，原生 V5 端点 + mark-price-kline 折算 `open_interest_usd`，偏差 0.51% 实测验证）
- **交易所后缀分区隔离**：`BTC_USDT-OKX` / `-BINANCE` / `-BYBIT` 物理隔离；交割合约确定性映射 `BTC/USDT:USDT-260904` → 原生 id `BTCUSDT-04SEP26`（validator 零改动）

### Engineering
- **读侧解析层**：`DataStore.resolve_symbol()` 显式优先级链 `(-OKX, -BINANCE, bare)`——web 读路径自动优先干净源、无后缀时零行为变化；否决透明 fallback（防混源静默污染回测）
- **web 写侧对齐**：station 下载落 `-OKX` 分区；tag/查询复用同一 resolver
- **时间戳单位自适应**：修复 Binance archive 近期月份 `openTime` 毫秒→微秒变更导致的未来泄漏误报（`_normalize_epoch_ms` 幅值判别）
- **生产数据迁移**：Binance 存量全量重跑至 `-BINANCE` 分区（5 组：BTC 1d+1h / ETH/SOL/XRP 1h，重叠率 100%、close 中位偏差 ≤0.013%）
- **迁移工具**：`scripts/archive_legacy_partitions.py`（dry-run 默认、显式映射表、归档目的地在 parquet_dir 外、meta relabel 保住不可再生 OKX 元数据历史）

### Docs
- README 数据源章节重写（三所命令矩阵）；知识库沉淀 Binance 时间戳陷阱与后缀隔离架构决策

## [0.8.0] — 2026-08-18

### Features
- **覆盖率 100/100 达成**：`quantflow/**` 行覆盖 100% + 分支覆盖 100%（18568 stmts / 5386 branches 全 0 缺失）
- 新增 35 个覆盖率测试文件（约 1400 用例）：common/indicators/data/signal/strategy/web/cli 全层覆盖
- `cli/main.py`（1787 行 Typer 应用）行+分支双 100%，含 `_display_*` 辅助、ai/kol 命令全分支
- 测试套件 3423 passed（基线 2421 → 3423），无回归

### Engineering
- `pyproject.toml` coverage `fail_under` 75 → **100**（行+分支双维度）
- pragma 豁免仅用于真正不可达/外部 IO 路径：35 处（21 个文件），全部附理由注释
- 移除 14 个错误断言测试（10 templates + 4 engine），直接删除而非 @skip 掩盖

### Docs / Hygiene
- README 版本徽标 v0.8.0 + 覆盖率 100% 数据
- Release notes: docs/release/v0.8.0.md
- .gitignore 补充 `data/station_history_test_*/` 运行时产物规则
- 清理本地临时/缓存/构建产物（.venv_old、no/、coverage.json、__pycache__ 等）


## [0.7.2] — 2026-08-12

### Features
- L6 research GO export: loader + Prometheus gauges + MonitoringSink + `scripts/export_research_go_panel.py`
- Engineering uplift: paper session lifecycle / reconcile / kill-switch integration tests
- Coverage floor fail_under 75; CLI paths measured (omit only tests/*)
- Optional full-history gitleaks workflow (pinned v8.24.3; not a PR gate)

### Fixes
- W14 GO fixtures/scripts stamp `execution_path=paper_replay` + data_fingerprint
- L1 CVD helpers moved to `quantflow.common.cvd` (no data→indicators import)
- paper_day_streak late-bind SESSIONS_DIR/LEDGER_PATH for test monkeypatch

### Docs / Hygiene
- AGENTS/CLAUDE parity = paper↔live only; docker/docker-compose.yaml; coverage ≥75
- requirements-lock refreshed for 0.7.x surface
- .gitignore: `.workflow/tmp-*`
- Release notes: docs/release/v0.7.2.md


## [0.7.0] — 2026-08-11

### Features
- IMP-01: dual-path / path_b_oos attach honest vectorized promotion_path + data_fingerprint (not fake paper_replay GO)
- IMP-02: Path B multi-window OOS default n_windows=6 + cost_attachment (fee_slip_grid + funding_tca)
- IMP-03: Feature Store PIT audit helper (`pit_audit`) fail-closed on lookahead
- IMP-04: multi-symbol dual-path research report (≥2 OKX symbols; no combined_score)
- IMP-05: session health Prometheus gauges + alert taxonomy ops doc

### Research docs
- OSS adversarial residual improvement plan + team-swarm map
- dual-path research OS IMP status sections
- docs/ops/alert-taxonomy-session-health.md
- Release notes: docs/release/v0.7.0.md

### Cleanup
- Untrack `.workflow/scratch/` runtime logs/screenshots (~153 files)
- .gitignore: workflow tmp/archive/scratch/search-daemon artifacts
- Local cache purge (__pycache__, pytest/ruff)

### Tests
- Focused suites: dual_path/path_b_oos/promotion_path, pit_audit, multi_symbol_dual_path, session_health

## [0.6.0] — 2026-08-10

### Features
- W18: ZigZag real high/low pivots, confirmed-only default, degraded consensus flag; bar BBO feed path; dormant factors wired (supertrend/DEMA/stochRSI/Keltner/Donchian)
- W19: WaveInvalidationChecker exits, RSI divergence vs W1 peak, FeatureStore save keep-first; ticker BBO API; session_vwap + obv_slope
- W20: opt-in ticker BBO poll; bar-level cvd_proxy; Elliott WFO smoke (vectorized_smoke, not GO)
- W21: funding risk gate (pause / optional KillSwitch, default off); Elliott paper_replay smoke; fetch_trades + cvd_from_trades scaffold
- W14–W16 / OSS uplift already on main: promotion_path discipline, paper BBO fill opt-in, AI validation bypass, PauseReasonSet/ghost/preflight

### Research docs
- W17 research pack (small-team edge, wave repaint, antifuture/factors, orderbook micro)
- W18–W21 implementation notes under docs/research/
- Release notes: docs/release/v0.6.0.md

### Cleanup
- Untrack local DuckDB probes and station_history_probe JSONL
- .gitignore: data/*.duckdb, meta_merged, .workflow/recovery
- Local cache purge (__pycache__, pytest/ruff, gitleaks reports)

### Tests
- Focused suites for W18–W21 (wave/BBO/factors/funding/paper_replay/CVD)

## [0.5.0] — 2026-08-08

### Features
- Shared-book symbol-level Risk Parity (opt-in, default strategy-level)
- multi_symbol_replay / wfo_shared_rp research toolchain
- Honest WFO OOS comparison equal vs shared_risk_parity

### Docs
- docs/release/v0.5.0.md; public demo pack positioning

## [0.4.0] 鈥?2026-08-03

### Features (Wave 1: s1-integrity-foundation + s2-multisource-data)
- Checkpoint state store (quantflow/execution/state_store.py): crash-recovery persistence for trading sessions (atomic tmp+replace, schema versioning, fail-closed restore) 鈥?resolves ISS-20260803-004
- Exchange health monitor (quantflow/execution/exchange_health.py): single-exchange circuit breaker with sliding window error rate + rate-limit streak detection, hysteretic cooldown recovery 鈥?resolves ISS-20260803-003
- Market meta-data fetcher (quantflow/data/market_meta_fetcher.py): funding rate & open interest collection with self rate-limiting + polling floors + exponential backoff 鈥?resolves ISS-20260803-001
- FundingRateStrategy production feed wiring: OKX funding-rate-history 90-day cap + incremental accumulation

### Reliability & Integrity
- ReconciliationEngine production runtime integration (ISS-20260803-002): drift detection enforced in live/paper session lifecycle
- Session recovery: TradingSession.start restores checkpoint + verifies via ReconciliationEngine before new entries (fail-closed)
- Paper/live parity convergence (ISS-20260803-005): partial-fill, regime gate, params parity covered by new integration tests
- RiskEngine exchange-circuit-open interception: single signal-entry blocking point

### Testing
- Integration: test_backtest_paper_parity, test_funding_feed, test_meta_backfill, test_session_recovery (20 tests)
- Unit: test_dq_monitor, test_exchange_health, test_market_meta_fetcher, test_state_store, test_store (68 tests)
- Regression: execution/risk/reconciliation/alert-routing/order-manager (89 tests)
- Total: 177 tests passing

### Knowledge & Harvest
- benchmark-evolve session harvested: 5 wiki entries + S-BM2603-RD0 spec + 6 new issues (ISS-20260803-001..006)
- New knowhow: gap-grading methodology, data-single-source, HighFlyer principles, benchmark methodology, evolution DAG

## [0.3.1] 鈥?2026-08-02

### Features
- ReconciliationEngine comprehensive unit tests (20 tests)
- DQ Monitor InMemoryStateStore Redis fallback (14 tests)
- ALERT_ROUTING matrix + AlertDeduplicator + send_routed() (18 tests)
- OrderManager thread-safety tests (5 tests)

### Security & Reliability
- DQ Monitor graceful degradation: in-memory fallback when Redis unavailable (ISS-20260802-010)
- Smart alert routing prevents alert fatigue (ISS-20260802-005)

### Cleanup
- Removed stale dist/ build artifacts from version control
- Deduplicated issues.jsonl (53 unique issues, all resolved)

## [0.3.0] 鈥?2026-08-02

### Features
- Reconciliation layer (`quantflow/reconciliation/`): position drift detection, orphan order discovery, audit logging
- `GatewayBase.query_open_orders()` abstract method + `OpenOrder` model for exchange-side order visibility
- Data quality monitor (`quantflow/data/dq_monitor.py`): real-time data feed health checks
- Distributed tracing support (`quantflow/common/tracing.py`)
- Strategy factory (`quantflow/strategy/factory.py`): centralized strategy instantiation
- React + Vite frontend (`frontend/`) replaces legacy static web assets

### Security & Reliability
- OrderManager thread-safety hardening (REL-H7): RLock + atomic context manager for concurrent order access
- OKX/Paper gateway implement `query_open_orders()` for reconciliation
- Fail-closed gateway contract enforcement

### Monitoring
- Enhanced alerting pipeline (`quantflow/monitoring/alerts.py`): expanded alert types
- Operational Grafana dashboards (alert-rules-ops, operational-integrity)
- WCAG accessibility audit script (`scripts/wcag_audit.py`)

### Documentation
- Operations guide (`docs/operations-guide.md`)
- Release docs for v0.2.0
- Qoder integration docs (`docs/qoder/`)

### Tests
- New: `test_order_manager_thread_safety.py` 鈥?concurrent order lifecycle validation
- Removed: `test_innerhtml_choke_point.py` (superseded by frontend migration)
- Updated execution, gateway, and web app tests for new architecture

### Chores
- Migrated web UI from `quantflow/web/static/` to dedicated `frontend/` React app
- Repository cleanup: added ignore rules for backups, trash, temp files, PID files
- Workflow knowledge base expansion (6 new knowhow entries)

## [0.2.0] 鈥?2026-08-01

### Security
- ISS-004: Global `_redact_processor` in structlog pipeline prevents credential leakage
- ISS-006-retro: Adversarial redaction tests (near-miss, benign-collision, env-unset)

### Architecture
- ISS-002: `IndicatorComputer` Protocol injection eliminates L1鈫扡2 layer violation
- ISS-011: CLI benchmark extracted to `BenchmarkService` (401鈫?5 lines thin shell)
- ISS-010: Strategy metadata migrated from hardcoded Python to YAML config

### Features
- ISS-003: OKXGateway WebSocket support via ccxt.pro (watch_ohlcv, watch_orders, reconnection)
- ISS-002-recursive: Recursive indicator dependency analysis CLI (`validate --method recursive`)
- Schema exposure module for LLM-safe data interface
- Mean reversion stop_loss_pct parameter (on_bar + vectorized paths)

### Performance
- ISS-001: CPCV O(n虏) memory optimization (peak memory halved)
- P0-verify: 4-strategy byte-for-byte regression guard baseline established

### Bug Fixes
- ISS-005: CLI research/optimize/validate now pass date filters to DataStore
- ISS-007: ZigZag low-volatility fallback when consensus pivots empty
- ISS-001-vectorbt: Spec contradiction resolved (deprecated, numpy vectorization confirmed)

### Tests
- 100+ new tests across all fixes
- 1690 total tests passing
- M4 Phase 6 multi-symbol integration tests (65 tests)
- Architecture guard tests (data layer import, redaction processor, catalog YAML)

### Workflow
- 17 open issues resolved (17鈫?)
- Roadmap P0-verify passed
- State blockers cleared

## [0.1.3] - 2026-06-07

### Added
- Added `quantflow/strategy/templates/_runtime.py` to share numeric helpers across event-driven strategy hot paths.
- Added `runtime.three_strategy_bars_per_sec` to `quantflow benchmark` so the three-strategy `on_bar()` path can be checked as a release gate.
- Added the `docs/release/v0.1.3/` release-candidate documentation set.

### Changed
- Promoted project version metadata from `0.1.2` to `0.1.3` so source, tag, and release assets can align with the current `HEAD`.
- Reworked `trend_following`銆乣mean_reversion` 鍜?`volatility_breakout` 鐨?event-driven path to use incremental calculations instead of rebuilding a DataFrame on every bar.
- Regenerated `requirements-lock.txt` from a clean installed-wheel environment and removed the stale editable Git entry plus host-only development dependencies.
- Raised the minimum `aiohttp` requirement to `3.14.0`.
- Restricted Hatch `sdist` selection to release-safe files only, excluding `.workflow`銆乣.codegraph`銆乣tests` and other non-release artifacts from source packages.

### Fixed
- Refreshed release checksum and manifest generation against the `v0.1.3` artifact names.
- Expanded CLI and strategy tests so the incremental runtime path stays aligned with the vectorized signal path.

## [0.1.2] - 2026-06-03

### Fixed
- Fixed the release workflow so GitHub Release assets include only the current version's package and checksum files.
- Fixed release metadata generation so manifest entries carry explicit checksum file paths for the active version.

### Changed
- Promoted the clean release candidate from `v0.1.1` to `v0.1.2` after detecting that the previous release mixed in historical checksum assets.

## [0.1.1] - 2026-06-03

### Added
- Added `scripts/build_release.py` to build release artifacts, checksums, and a release manifest from one command.
- Added `.github/workflows/release.yml` to publish GitHub Release assets from a `vX.Y.Z` tag.
- Added `dist/SHA256SUMS.txt` and `dist/release-manifest.json` as release metadata outputs.

### Changed
- Promoted the release process from manual artifact collection to a tag-driven, repeatable workflow.
- Updated release documentation to treat automated release publication as part of the delivery standard.
- Reserved `v0.1.0` as the historical baseline and moved the current release candidate to `v0.1.1` for source/tag consistency.

## [0.1.0] - 2026-06-03

### Added
- Added four new strategy templates: `volatility_breakout`, `funding_rate`, `momentum_rotation`, and `ml_ensemble`.
- Added package build verification and CLI smoke checks to GitHub Actions CI.
- Added release documentation set under `docs/release/v0.1.0/`.
- Added `requirements-lock.txt` for reproducible environment capture.
- Added SHA256 checksum files for source and wheel distributions.

### Changed
- Hardened Docker packaging and compose deployment flow for clean install and health checks.
- Improved installed-package runtime path handling for CLI config resolution.
- Improved environment preflight checks in `scripts/check_env.py`.
- Tightened backtest correctness around equity continuity and trade PnL handling.
- Raised release readiness with packaging, deployment, and verification artifacts.

### Fixed
- Fixed release-chain runtime issues affecting packaged CLI execution.
- Fixed transient data fetch failure handling so the trading loop retries instead of terminating.
- Fixed `ruff format` drift caught by CI.
- Fixed missing runtime dependency on `scikit-learn`.

### Security
- Verified no hard-coded live credentials are present in tracked source files.

### Known Issues
- Real exchange execution still requires operator-provided environment variables such as `OKX_API_KEY`, `OKX_SECRET`, and `OKX_PASSPHRASE`.
- Optional ML extras such as `torch` and `transformers` are not installed by default and must be added explicitly when enabling the corresponding strategy path.

