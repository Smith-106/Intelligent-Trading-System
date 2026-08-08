# ISS-006 Pipeline Audit + Wiring (Wave D1–D3)

## Sequence (before → after)

```
BEFORE:
  ai research → discover_factors → print table → (discard)
  ai train    → IndicatorEngine FeatureStore only → validation_gate → report JSON
  ai register → ModelRegistry (GO→paper / else rejected)

AFTER (this wave):
  ai research → discover_factors (CLI|baseline degrade) → save data/ai_factors/{sym}/
  ai train    → factors_json | latest.json materialize → else FeatureStore (logged)
              → validation_gate → data/ai_reports/{model_id}.json
  ai register → ModelRegistry status=paper | rejected  (no promote_to_live this round)
```

## Breakpoints (file:line anchors)

| Gap | Location | Fix |
|-----|----------|-----|
| research discarded output | `cli/main.py` `_ai_factor_mining` | `save_discovered_factors` |
| train ignored discoveries | `_ai_train` | `--factors-json` + latest pointer + `materialize_factor_frame` |
| qlib hard-stop blocked paper path | `rd_agent.discover_factors` | degrade to pandas baseline without raising |
| OHLCV in factor artifacts | N/A (new) | payload = name/formula/IC only |

## Commands

```bash
quantflow ai research --symbol BTC/USDT
quantflow ai train --symbol BTC/USDT --factors-json data/ai_factors/BTC_USDT/latest.json
quantflow ai register --model-id model-<hash>
```

No LLM / no qlib: research still writes baseline factors; train still runs gate (decision may be NO-GO).

## Tests

`pytest tests/unit/test_rd_agent.py` — 20 passed (incl. persistence + degrade).


## D4–D7 smoke (2026-08-08)

- Path: baseline degrade (no qlib) → `data/ai_factors/BTC_USDT/…` → materialize 5 cols → `AITrainingPipeline.train` → **NO-GO** (CPCV PBO≥0.5) → `ModelRegistry.register` **rejected**
- Pipeline integrity: **PASS** (fail-closed gate worked; status never live)
- ISS-20260803-006 → **resolved**; optional true `rdagent` CLI+LLM = future residual only
