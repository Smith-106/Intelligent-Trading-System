# T036 — RD-Agent / AI validation bypass（禁止直连 live）

**Date**: 2026-08-10  
**Option B residual**: [option-b-evolution-roadmap.md](./option-b-evolution-roadmap.md)  
**Prior**: [iss-006-pipeline-audit.md](./iss-006-pipeline-audit.md)

---

## Contract

```text
ai research / rdagent  →  factors (data/ai_factors)
        ↓
ai train  /  ai bypass →  validation_gate + report (data/ai_reports)
        ↓
ai register            →  paper | rejected   (cost + W14 path)
        ✗
promote_to_live        →  FORBIDDEN if ai_lane=validation_bypass
```

| Rule | Enforcement |
|------|-------------|
| No live from AI CLI | `quantflow ai *` never calls `promote_to_live` |
| Bypass stamp | `ai_lane=validation_bypass`, `ai_live_blocked=true` |
| Registry | `ModelRegistry.promote_to_live` raises if stamp present |
| Vectorized train | `execution_path=vectorized` → **W14 refuses paper GO** until paper_replay re-eval |
| Degrade | No qlib/LLM → pandas baseline factors (existing) |

---

## Commands

```bash
# One-shot research → train → stamp → optional register attempt
quantflow ai bypass --symbol BTC/USDT

# Classic split steps (unchanged)
quantflow ai research --symbol BTC/USDT
quantflow ai train --symbol BTC/USDT --factors-json data/ai_factors/BTC_USDT/latest.json
quantflow ai register --model-id model-<hash>
```

---

## Module

- `quantflow/strategy/ai_validation_bypass.py` — `run_ai_validation_bypass`, stamps, live assert  
- CLI action: **`bypass`**  
- Tests: `tests/unit/test_ai_validation_bypass.py`

---

## Explicit non-goals

- Auto-wire AI models into live OKX  
- Skipping fee×slip / funding_tca / paper_replay for paper GO  
- Replacing B0 trend_following with ML ensemble  

*T036: AI is a research side-door into validation — not an execution path.*
