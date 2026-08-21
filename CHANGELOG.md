# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

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

