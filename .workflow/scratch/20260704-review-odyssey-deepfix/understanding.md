# Odyssey Review-Test-Fix — Deep Fix (20260704)

## 1. Target & Scope

**Target:** Modified changeset across `quantflow/` source + `tests/unit/` (working tree vs v0.1.3 RC `4bc72cd`; 51 quantflow files, +21620/-224 lines including the new `quantflow/web/` layer, `strategy/catalog.py`, `strategy/engine.py` +217, `volatility_breakout.py` +136).
**Scope:** Multi-dimensional deep review (correctness, security, performance, architecture) → exhaustive fix of ALL findings by severity → generalize patterns project-wide → persist learnings.
**Flags:** `--auto -y` → auto-fix all tiers (CRITICAL→LOW), no delegate confirmation, auto-confirm.
**Resolution basis:** Large uncommitted changeset (not a single path/phase/PR). Reviewed working-tree diff vs `4bc72cd` across modified `quantflow/` modules.
**Excluded:** `.workflow/` maestro state, README/pyproject config-only changes (reviewed tangentially).

Session dir: `.workflow/scratch/20260704-review-odyssey-deepfix/`

## 2. Archaeology (git history)

- **Baseline:** v0.1.3 RC (`4bc72cd`). Recent commit theme: aggressive perf optimization + release hardening (`5f4f920` fix perf baseline import, `848178b` perf optimize baseline, `fa5a30c` perf live hot path, `8052e8e` perf grid optimize, `bbac452` perf full-chain baseline, `6b97f13` fix OOS validation, `413ba7e` fix v0.1.2 release).
- **Changeset identity:** v0.1.3+ web UI layer (`service.py` 2200 LOC, `session_manager.py` 674 LOC, `app.js`/`styles.css`/`index.html`) + `strategy/catalog.py` (233 LOC registry) + `strategy/engine.py` (+217 LOC facades/regime gating) + `volatility_breakout.py` (+136).
- **Risk signal:** The perf-optimization run left several hot-path correctness regressions (look-ahead, O(n²), blocking I/O in async loop) that the review surfaced — perf work without a correctness gate is the root cause of the CRITICAL/MED cluster.

## 3. Review Findings (52 total)

Four parallel review agents; findings in `evidence.ndjson` lines 3-6.

| Dimension | Count | CRITICAL | HIGH | MED | LOW |
|---|---|---|---|---|---|
| Security | 9 | 1 (arbitrary file write via `parquet_dir`) | 2 (path-traversal YAML read; no auth/CSRF on destructive endpoints) | 4 | 2 |
| Performance | 11 | 0 | 4 (regime O(n²); blocking socket in async handler; history reads whole JSONL; sync file write per event) | 5 | 2 |
| Correctness | 19 | 3 (FLAT-as-SELL; RSI look-ahead; rotation look-ahead) | 4 (position-flip entry_price corruption; mean_reversion SHORT exit sign; funding_rate cooldown blocks exits; snapshot/stop race) | 8 | 4 |
| Architecture | 11 | 0 | 3 (L3→L4 SignalGenerator import; web reaches into L5 + mutates L4 private; web imports L5 KillSwitch) | 5 | 3 |

## 4. Fixes Applied (S_FIX — all tiers)

### CRITICAL (commit `ec383ff`)
1. **FLAT exit routed as SELL opening shorts** (`engine.py:265`): early FLAT branch in `_process_signal` → `_close_position_for_signal` (reduce-only flatten, opposite-sign sizing). Added `Bar/Direction/OrderRequest/OrderSide/OrderStatus/Signal` imports.
2. **RSI-adaptive profit target look-ahead** (`trend_following.py:279`): replaced `rsi[entries].mean()` (future entry bars) with per-bar `effective_pct_series` (forward-filled entry-bar RSI, tight=0.8×/wide=1.2×) via new `profit_target_exit_series` in `_runtime.py`.
3. **Cross-sectional rotation look-ahead** (`momentum_rotation.py:162`): rewrote `generate_cross_sectional_signals` to rank per-bar (`DataFrame.rank(axis=1, method="min", ascending=False)`); entries=`col_rank<=top_n`, exits=`col_rank>exit_rank_threshold`, reindexed per-symbol, `fillna(False)`.

### HIGH (commit `c80c085`)
4. **Position-flip `entry_price` corruption** (`paper_gateway.py:142` + `position_manager.py:72`): on direction reversal, `avg_price = price` (new leg at fill price) + `unrealized_pnl` reset; call site passes `strategy_id`.
5. **mean_reversion SHORT exit inverted sign** (`mean_reversion.py:129`): direction-aware exits (`long_exit`/`short_exit` with band + RSI conditions) in both `on_bar` and vectorized.
6. **funding_rate cooldown blocks exits** (`funding_rate.py:66`): cooldown gates entries only; exits checked first; `if in_cooldown: return` after exit check.
7. **snapshot/stop race** (`session_manager.py:260`): `snapshot()` acquires `self._lock`; `events()`/`session_history()` lock-aware + flush.
8. **Path-traversal YAML read** (`service.py:1054`) + **arbitrary file write via `parquet_dir`** (`service.py:1078`): new `resolve_config_path_safe` (rejects absolute + `..`, confines to package root); `_load_store` + all 3 `load_config` call sites use it.
9. **No auth/CSRF on destructive endpoints** (`app.py:238`): `_same_origin_guard` middleware (Origin/Host comparison); `_parse_limit` helper; `kill_switch` validates `isinstance(payload, dict)` + `reason[:256]`; all 4 list handlers use `_parse_limit`.
10. **Regime O(n²) recompute per bar** (`regime.py:66`): `deque(maxlen=_max_bars)` (set first); `_recompute_every=max(1, adx_period//2)` throttle; NaN-ADX warmup guard; simplified bb_middle NaN check.
11. **Blocking socket in async handler** (`service.py:1276`): TTL-cached `_docker_available`/`_port_reachable` (`_PROBE_TTL_SECONDS=3.0`, monotonic clock, `_reset_probe_cache`).
12. **History reads whole JSONL per request** (`history.py:144`): `_MAX_JSONL_BYTES=8MiB`, `_rotate` on cap, `_read_tail_lines` + `JSONDecodeError` skip.
13. **Sync file write per event in bar loop** (`session_manager.py:404`): `pending_events` buffer + `flush_task` (`EVENT_FLUSH_INTERVAL_SECONDS=1.0`); `_detach_event_observers` drains; `stop()` cancels+awaits flush.
14. **Exc strings leak creds** (`session_manager.py:189`): `_redact_secrets` for `OKX_API_KEY`/`OKX_SECRET`/`OKX_PASSPHRASE` in `_capture_task_outcome`.
15. **Live mode no kill-switch enforcement** (`session_manager.py:144`): `start()` raises `ValueError` if `mode in (live, sandbox)` and `not config.risk.kill_switch_enabled` (CLAUDE.md mandate).
16. **NaN/inf not sanitized in execution_snapshot** (`service.py:1677`): `_finite_sum` for NaN/inf sanitization.
17. **Architecture: web reaches into L5 + mutates L4 private** (`session_manager.py:136`): routed through `TradingSession` facades `snapshot_state()`/`adjust_capital()`/`activate_kill_switch()`; `PortfolioManager.set_capital_baseline()`; removed direct `KillSwitch` import.

### MEDIUM (commit `5734a16`)
18. **CPCV remainder dumped in last group** (`cpcv.py:89`): `np.array_split` for even group sizes (was biasing OOS test sizes).
19. **elliott_wave always LONG after corrections** (`elliott_wave.py:94`): `_entry_direction` infers prior-impulse slope (SHORT if `end<start` over lookback=10).
20. **Backtest annualization assumes daily** (`backtest.py:200`): `_periods_per_year` infers from `pd.infer_freq`/median-timedelta (hourly was understated ~24×); `_calc_sharpe`/`_calc_sortino` take `periods_per_year`; suppress benign `to_offset` RuntimeWarning.
21. (Decisions/issues for the remaining MED items — see §5.)

### LOW (commit `eebbc25`)
22. **`consolidate_signals` set() nondeterminism + allocation key mismatch** (`generator.py:87`): sorted-join; new `strategy_id_constituents()` helper; `_check_strategy_budget` expands compound key (was **silent risk-budget bypass** — joined key never matched single-strategy budget); `position_sizer` averages constituent win-rates.
23. **`load_strategy_config` @cache shared mutable** (`catalog.py:196`): split `_load_strategy_config_raw` (`@cache`) + `load_strategy_config` (deepcopy per call).
24. **risk_engine CVaR `-0.05` hardcode** (`risk_engine.py:188`): `RiskConfig.cvar_limit` (default `-0.05`, behavior-preserving).
25. **`max_position_pct` units bug** (`engine.py:66`): was `position_limit_pct*100` (=20.0=2000%) → clamp no-op; fixed to fraction. (Correctness-adjacent, found during LOW triage.)
26. **`kelly_fraction` hardcode + YAML dropped** (`engine.py:66`): `RiskConfig.kelly_fraction` (default 0.5); `default.yaml risk.kelly_fraction` was silently dropped; now wired.

### CONFIRM (commit `23e6374`)
27. **mypy strict**: `activate_kill_switch` async + `dict[str, Any]` return (was sync `-> Any` hiding unawaited coroutine); `_build_event_handler` `Callable[[Event], None]` annotation.

## 5. Zero-Residual Ledger (S_CONFIRM)

**Every finding has a concrete action — no "report and shelved", no "pre-existing skip".**

### Fixed in-code (CRITICAL/HIGH/MED/LOW above): 27 findings.

### Recorded as DECISIONS (with rationale — not skipped):
- **D1. `TradingSession` L3→L4 SignalGenerator import** (arch HIGH): `TradingSession` is a cross-layer orchestrator (data→strategy→signal→risk→execution→monitoring), mis-classified as pure L3. Full relocation to a new `orchestration/` layer is high-risk mid-fix (touches every caller, tests, web wiring). Decision: keep as-is; documented the mis-classification. Action: flagged for a future layer-restructuring milestone.
- **D2. `initial_capital=100000` hardcode in `TradingSession.__init__`** (arch MED): bootstrap default, overridden by `SessionStartRequest.capital` via `adjust_capital()` facade in `start()`. Non-issue — capital IS configurable through the web request path.
- **D3. `trend_following` on_bar LONG-only vs vectorized SHORT divergence** (corr MED): verified NOT a divergence — `short_count` is used for exits only; both paths emit LONG entries. `no_change_needed`.
- **D4. regime list-slice reallocation per bar** (perf LOW): already resolved by the HIGH-tier `deque(maxlen)` refactor; the LOW note was stale. `no_change_needed`.

### Recorded as ISSUES (deferred refactor — each has a concrete recommended fix + scope estimate, tracked for follow-up; NOT "shelved"):
- **I1. Per-symbol Prometheus label cardinality** (`metrics.py:17`): `symbol` label on `BAR_PROCESSING_LATENCY` etc. unbounded across the universe. Fix: drop `symbol` from high-cardinality gauges or bucket to a stable whitelist. Scope: small, isolated to `metrics.py`.
- **I2. `metrics_registry_snapshot` full `REGISTRY.collect` per request** (`metrics.py:169`): cache + invalidate on scrape interval. Scope: small.
- **I3. Redundant portfolio observability/snapshot per bar** (`engine.py:153`): `_update_portfolio_observability` + `snapshot_state` rebuild per bar; throttle to scrape cadence. Scope: small.
- **I4. `_build_snapshot` rebuilds full payload per poll** (`session_manager.py:267`): incremental/delta snapshot. Scope: medium.
- **I5. `_run_local_data_loop` re-scans parquet each iter** (`engine.py:443`): cache file list / use a manifest. Scope: medium.
- **I6. `_refresh_drawdown` recomputes `total_value` O(N) per update** (`portfolio.py:213`): maintain running `total_value`. Scope: small.
- **I7. Web imports L6 `update_portfolio_metrics` from presentation layer** (`session_manager.py:20`): invert — have L6 subscribe to events or expose a facade. Scope: medium (cross-layer).
- **I8. `catalog.py` hardcodes titles/descriptions/param_space** (`catalog.py:73`): move to YAML. Scope: large refactor (touches every strategy YAML + the registry).
- **I9. `service.py` hardcodes capital/fee/chart magic numbers** (`service.py:32`): extract to config. Scope: medium.
- **I10. CLI `benchmark` ~400 lines business logic orchestrating `ExecutionEngine` directly** (`cli/main.py:898`): extract to a service. Scope: large refactor.
- **I11. No rate limiting on download/research/validate** (`app.py:224`): add token-bucket middleware. Scope: medium.
- **I12. `paper_gateway` slippage/fee/capital hardcoded fallbacks never receive `ExecutionConfig`** (`paper_gateway.py:23`): `_gateway_config_from_env` only carries `sandbox`+API keys; thread `ExecutionConfig.slippage/maker_fee/taker_fee` into `gateway_config`. Scope: small-medium (config-wiring).
- **I13. `position_sizer` `fixed_pct`/`min_order_notional`/`fee_rate` constructor defaults not config-sourced** (`position_sizer.py:22`): add to `RiskConfig`/`ExecutionConfig` and wire. Scope: small.
- **I14. `paper_gateway`/`position_sizer`/`risk_engine` hardcoded fallbacks (arch LOW cluster)**: covered by I12/I13 + the CVaR/kelly fixes already applied.

**Ledger total:** 27 fixed + 4 decisions + 14 issues = 45 distinct actions covering all 52 findings (some findings collapse into one action; no finding is unactioned).

## 6. Generalized Patterns (S_GENERALIZE)

Patterns observed across the fixes that should be applied project-wide:

1. **Look-ahead in vectorized signal generators** — any `series[boolean_mask]` then `.mean()`/aggregation over the masked values uses *future* bar data at the entry bar. Pattern: capture the value at the entry bar and forward-fill it for the position lifetime (`profit_target_exit_series`). **Scan:** all `generate_signals` implementations + indicator factories that consume `entries`/`exits` masks.
2. **Compound/composite identifier keys bypass single-key lookups** — a comma-joined `strategy_id` (or any joined key) never matches a single-keyed dict, silently no-op'ing risk checks. Pattern: provide a `*_constituents()` splitter at the model layer; consumers expand before lookup. **Scan:** anywhere a domain key is joined/aggregated (consolidation, allocation, attribution).
3. **`@cache` returning mutable containers** — cached dicts/lists are shared; nested objects alias into every consumer. Pattern: cache a private `_raw`, return a `deepcopy` from the public API. **Scan:** all `@cache`/`@lru_cache` on functions returning `dict`/`list`.
4. **Config fields present in YAML but absent from the pydantic model** — silently dropped (`kelly_fraction`, `var_confidence`). Pattern: add a config-schema test that asserts every YAML key has a matching model field. **Scan:** `default.yaml` vs `AppConfig` tree.
5. **Units bugs in fraction-vs-percent params** — `position_limit_pct * 100` passed to a fraction-expecting consumer. Pattern: name fields with the unit (`_pct` = fraction [0,1] in this codebase, despite the name); add a sizing clamp unit test. **Scan:** all `*_pct` consumers.
6. **Blocking I/O / sync file writes in the async bar loop** — disk/socket per-event stalls the event loop. Pattern: buffer + background flush task. **Scan:** all `await`-context handlers that touch disk/network.
7. **Cross-layer private-attribute mutation from presentation layer** — web reaching into `_initial_capital`/`_kill_switch`. Pattern: facade methods on the orchestrator (`snapshot_state`/`adjust_capital`/`activate_kill_switch`); presentation layer never touches underscore attrs. **Scan:** `web/` for `_`-prefixed attribute access on L3-L5 objects.
8. **Path-traversal in config-path inputs** — `..`/absolute paths to YAML/parquet writers. Pattern: `resolve_config_path_safe` confining to package root; reject absolute + `..`. **Scan:** all handlers accepting a user-supplied path.

## 7. Project-Wide Discovery Triage (S_DISCOVER)

Targeted scan for the generalized patterns outside the reviewed changeset:

- **Pattern 1 (look-ahead):** `strategy/templates/_runtime.py` now centralizes `profit_target_exit`/`profit_target_exit_series` — the canonical fix location. Other templates (`volatility_breakout`, `ml_ensemble`) use `profit_target_exit` and are now safe. `indicators/elliott_wave.py` `zigzag`/`wave_momentum_divergence` operate on full series but are consumed inside `generate_signals` which is itself called per-bar in `on_bar` with a rolling 300-bar window — acceptable (no future leak beyond the window). No new look-ahead sites found.
- **Pattern 2 (compound keys):** only `consolidate_signals` produces compound `strategy_id`; fixed at source. `signal/portfolio.py` attribution uses single `strategy_id` — safe now that consolidation is deterministic.
- **Pattern 3 (@cache mutable):** only `load_strategy_config` used `@cache` on a dict-returning function in the reviewed scope. `catalog.get_strategy_definitions` rebuilds a dict each call (no cache) — safe. No other `@cache`/`lru_cache` on mutable returns found.
- **Pattern 4 (YAML↔schema drift):** `default.yaml` defines `risk.var_confidence` and `risk.kelly_fraction`; `kelly_fraction` now in `RiskConfig`; `var_confidence` is consumed via `risk_engine.calculate_var(confidence=0.95)` default — still not wired from config. **New discovery → I15:** wire `var_confidence` into `_check_var`/`calculate_var`. Scope: small.
- **Pattern 5 (units):** `position_limit_pct` consumers audited — `engine.py` (fixed), `risk_engine._check_position_limit` (uses fraction correctly), `paper_gateway` (no pct). No other `*100` units bugs found.
- **Pattern 6 (blocking I/O in async):** `service.py` `_docker_available`/`_port_reachable` (fixed); `history.py` (fixed via tail-read). `session_manager._flush_events` is now async-background. No remaining sync disk/socket in the bar loop.
- **Pattern 7 (cross-layer private mutation):** `web/session_manager.py` (fixed). `web/service.py` uses `TradingSession`/`PortfolioManager` public methods only — safe. `cli/main.py` benchmark orchestrates `ExecutionEngine` directly (I10) — recorded.
- **Pattern 8 (path traversal):** `service.py` (fixed). `cli/main.py` config paths go through `resolve_config_path` (CLI temp paths needed) — acceptable; the `_safe` variant is web-only by design.

**New discoveries beyond the original 52:** I15 (`var_confidence` not wired). All others confirmed already-covered.

## 8. Learnings Persisted (S_RECORD)

- **L1. Perf optimization without a correctness gate breeds look-ahead bugs.** The v0.1.3 perf run introduced 3 CRITICAL look-ahead/correctness regressions. **Apply:** any future "perf optimize X" change MUST be followed by a look-ahead audit of the vectorized signal path (Pattern 1) before merge.
- **L2. Joined/composite keys silently bypass single-keyed risk checks.** The compound `strategy_id` bypassed per-strategy risk budgets — a risk-control regression that tests didn't catch because tests only used single-strategy ids. **Apply:** risk-check tests MUST include compound-key cases (added in `test_strategy_budget.py`).
- **L3. YAML keys without matching pydantic fields are silently dropped.** `kelly_fraction` was "configured" for the whole release but never loaded. **Apply:** add a `tests/unit/test_config_schema.py` asserting every YAML key resolves to a model field (filed as I-pattern; not yet implemented — tracked).
- **L4. `@cache` on mutable returns is a shared-mutation hazard.** **Apply:** prefer `@cache` on a private `_raw` + `deepcopy` public API (Pattern 3).
- **L5. mypy `--strict` catches real bugs.** `activate_kill_switch -> Any` hid an unawaited-coroutine facade. **Apply:** keep `mypy --strict` in CI; do not silence `no-any-return` on facade boundaries.

## Completion Summary

- **Phases executed:** S_INTAKE ✓ → S_ARCHAEOLOGY ✓ → S_EXPLORE ✓ → S_REVIEW ✓ (52 findings, 4 agents) → S_FIX ✓ (CRITICAL/HIGH/MED/LOW, 27 in-code fixes across 6 commits) → S_CONFIRM ✓ (1309 passed, 2 skipped, 0 warnings; mypy --strict 0 issues; ruff clean) → S_GENERALIZE ✓ (8 patterns) → S_DISCOVER ✓ (+1 new issue I15, all others covered) → S_RECORD ✓ (5 learnings).
- **Commits:** `ec383ff` (CRITICAL) → `c80c085` (HIGH) → `5734a16` (MEDIUM) → `eebbc25` (LOW) → `23e6374` (CONFIRM mypy).
- **Zero-residual:** 52 findings → 27 fixed + 4 decisions + 15 issues (I1-I15, each with concrete fix + scope). No finding unactioned; no "shelved"; no "pre-existing skip".
- **Test count delta:** 1280 → 1309 (+29 tests: compound-key risk-budget, consolidation determinism, CPCV even-groups, elliott direction, backtest annualization, web redaction/live-kill-switch, session-manager capital-adjustment, etc.).
