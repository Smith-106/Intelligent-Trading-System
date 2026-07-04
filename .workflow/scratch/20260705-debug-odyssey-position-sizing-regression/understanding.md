# Odyssey Debug — Position Sizing Regression Investigation (20260705)

## 1. Issue & Scope

**Issue:** Did the LOW-tier fix in commit `eebbc25` (`max_position_pct=config.risk.position_limit_pct`, was `* 100`) silently regress engine-driven trade sizing? The clamp went from a 2000% no-op to an active 20% cap — a potential 10-100x reduction in max order notional.
**Scope:** Full sizing pipeline: `TradingSession._process_signal` → `PositionSizer.size` → `* allocation` → `submit_order`. Plus the interaction with consolidation, per-symbol limits, and config wiring.
**Template:** `regression` (git bisect/blame + boundary check).
**Flags:** `--auto -y` (no delegate confirmation, auto-confirm).

Session dir: `.workflow/scratch/20260705-debug-odyssey-position-sizing-regression/`

## 2. Archaeology

- `git blame -L 60,75 quantflow/strategy/engine.py`: the `PositionSizer` construction at line 65-72 was original (`44b98c9`, v1.0, 2026-06-02) with `max_position_pct=config.risk.position_limit_pct * 100`. The `* 100` units bug existed since project inception.
- `eebbc25` (2026-07-05, LOW-tier review fix) changed it to `max_position_pct=config.risk.position_limit_pct` and also wired `kelly_fraction=config.risk.kelly_fraction` (was hardcoded `0.5`).
- The clamp was therefore a no-op for the **entire project lifetime** (v1.0 → v0.1.3 RC → review fix). The fix activated it for the first time — a genuine behavior change, not a regression.

## 3. Exploration

- **Call chain:** `Engine._process_signal` (engine.py:267) → `PositionSizer.size(signal, portfolio, strategy_win_rates=self._strategy_win_rates)` with **default** `win_rate=0.5, win_loss_ratio=2.0` → result `* allocation` (line 270) → `quantity = size / signal.price` → `ExecutionEngine.submit_order`.
- **Clamp placement:** `max_position_pct` clamps the **per-strategy** size **before** the `* allocation` multiply. Since consolidation (engine.py:189-200) reduces all per-symbol signals to ONE signal before `_process_signal`, there is exactly one `size()` call per symbol per bar → the clamp is a correct **per-symbol** limit (matching `position_limit_pct`'s "单标的最大仓位占比" semantics).
- **Test gap:** `test_position_sizer.py` constructs `PositionSizer` directly with fraction `max_position_pct` and **never** went through the engine `* 100` path. `test_max_position_cap` validated the clamp in isolation only. No test asserted the old no-op behavior, so the bug survived 5 commits + a perf run + a v0.1.3 RC.

## 4. Hypotheses

- **H1 [HIGH]:** The fix activates a previously-no-op 20% clamp, reducing order size for high-win-rate strategies (win_rate > ~0.62) from up to 27.45% to capped 20%. This is the **intended** risk-config enforcement, not a regression. Default-path trades (win_rate=0.5 → 12.5%) are unaffected.
- **H2 [MEDIUM]:** Multi-strategy same-symbol scenario could let each strategy take 20% of the same symbol, exceeding the documented single-symbol limit.

## 5. Root Cause

**H1 confirmed; H2 disproved.**

Empirical probe (`python -c`):
- Default `win_rate=0.5, strength=1.0` → `12475.0` (12.5%; clamp not engaged; **unchanged** by the fix).
- High `win_rate=0.7, strength=1.0` → fixed sizer `19960.0` (capped 20%) vs old buggy sizer `27445.0` (uncapped 27.45%).

`test_max_position_cap` (test_position_sizer.py:24) already validates the clamp works (`size <= 10000` at 10% cap). The engine simply wasn't wired to it.

**H2 disproved:** `consolidate_signals` reduces 2 LONG signals on BTC/USDT to one consolidated signal (`"momentum,trend"`, strength 0.65) → one `size()` call → one 20% clamp. Per-symbol limit holds.

**Root cause:** The `* 100` units bug (present since v1.0) was the **actual latent defect** — it silently ignored `position_limit_pct` for the entire project lifetime. The `eebbc25` fix is correct intended behavior, **not** a regression.

## 6. Fix & Confirmation

**Decision:** Keep the fix. No code change to the sizing logic itself.

**Concrete action (durable-ize the diagnosis):** Added `TestTradingSessionPositionSizingClamp.test_high_win_rate_order_clamped_to_position_limit` (test_engine_async.py) — drives `on_bar` end-to-end with a `win_rate=0.70` strategy whose raw Kelly size (27.45%) exceeds `position_limit_pct` (20%); asserts the submitted order notional ≤ `position_limit_pct * total_value` (≤20000).
- **Verified bidirectional:** under the old `* 100` wiring the order is `27445` → test FAILS; under the fixed wiring `19960` → test PASSES.

**Confirmation:** Full suite **1310 passed, 2 skipped, 0 warnings** (+1 regression test). mypy/ruff clean on touched code.

## 7. Generalization

**Pattern (root cause + fix):** *"Config field present in YAML but absent from the pydantic model is silently dropped at load time."* This is the same class of bug that hid `kelly_fraction` (fixed in `eebbc25`) and `var_confidence` (still unwired at debug start). Signature: a `default.yaml` key with no matching `RiskConfig`/`ExecutionConfig` field; consumer hardcodes the same default → appears to work, but the YAML is decorative.
- **Risk:** config changes have no effect; operators tune a value that does nothing (here, an operator lowering `position_limit_pct` to 0.10 would have seen **zero** change pre-fix).
- **Fix template:** (1) add the field to the pydantic model with the same default; (2) consume it from `self._config.*` instead of a hardcoded literal; (3) add a schema-drift guard test.

## 8. Discoveries

Project-wide scan for the generalized pattern (sibling bugs):

- **`*_pct * 100` units bugs:** `grep "_pct\s*\*\s*100"` → **0 hits**. The engine `* 100` was the only instance. Audited all `*_pct` consumers — `risk_engine._check_position_limit` uses `position_limit_pct` as a fraction correctly.
- **YAML↔pydantic schema drift:** probe walked `default.yaml` vs `AppConfig` → **1 hit: `risk.var_confidence=0.95`** missing from `RiskConfig`. This is the I15 issue noted in the prior review.
  - **Classification:** risk (config silently ignored). **Action: fix.**
  - **Fix applied:** added `RiskConfig.var_confidence: float = 0.95`; wired into `risk_engine._check_var` (percentile `(1-var_confidence)*100`), `calculate_var`, `calculate_cvar` (default `confidence=None` → uses config).
- **Schema-drift guard test added:** `TestConfigSchemaDrift.test_default_yaml_has_no_dropped_keys` walks `default.yaml` vs `AppConfig` and fails on any dropped key — durable guard so the `kelly_fraction`/`var_confidence` class of bug cannot recur.

**No other sibling bugs found.** The scan + guard cover the pattern project-wide.

## 9. Learnings

- **L1 (recurring root cause pattern):** *YAML key without a pydantic field is silently dropped.* Triggers: adding a config knob to YAML without updating the model; consumer hardcodes the same default so tests pass. Detection: schema-drift guard test (now added). Fix: add the field + consume from config. → category: recurring root cause pattern.
- **L2 (non-obvious):** *A units bug (`* 100` on a fraction field) survived a full release + perf run + RC because the clamp it disabled was never exercised at the engine wiring level — only in sizer-isolation tests.* Detection: integration tests must drive the full `on_bar → size → submit_order` path with inputs that engage each clamp, not just unit-test the sizer in isolation. → category: non-obvious workaround (test-strategy).
- **L3 (architecture boundary):** *Config consumers must read from `self._config.*`, never hardcode a literal that duplicates a YAML default.* The `risk_engine` hardcoded `0.95` while `default.yaml` declared `var_confidence: 0.95` — two sources of truth, one stale. Verification: the schema-drift test + a grep for hardcoded literals matching YAML defaults. → category: architecture boundary violation (config as single source of truth).

## Completion Summary

```
--- DEBUG ODYSSEY COMPLETE ---
Issue:      Did the eebbc25 max_position_pct units fix regress engine trade sizing?
Root cause: H1 confirmed — the *100 (2000% cap) was the real latent defect since v1.0;
            the fix is correct intended behavior, not a regression. H2 disproved.
Fix:        applied (regression test locking in the wired clamp) + sibling fix
            (var_confidence wired into RiskConfig/risk_engine) + schema-drift guard test
Patterns:   1 extracted (YAML<->pydantic schema drift)
Scan hits:  1 (var_confidence) — 1 confirmed, fixed; 0 remaining
Issues:     0 created (all fixed inline)
Decisions:  1 resolved (keep the fix), 0 pending
Learnings:  3 persisted (L1-L3)
Self-iter:  0 rounds (root cause confirmed on first hypothesis)
Goals:      6/6 done (0 skipped)
---
```

**Commits:** `1b313f9` (DIAGNOSE) → `a26f738` (FIX+CONFIRM regression test) → *(this commit)* (DISCOVER var_confidence fix + guard + RECORD).
**Test delta:** 1309 → 1312 (+3: position-sizing clamp, kelly/var-confidence wiring, schema-drift guard).
