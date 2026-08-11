# RD-Agent / AI validation bypass — offline job recipe (IMP-07)

**Date**: 2026-08-11  
**Status**: optional research job — **validation only, never live**  
**Authoritative design**: [t036-rdagent-validation-bypass.md](../research/t036-rdagent-validation-bypass.md)

## Hard constraints

| Rule | Value |
|------|--------|
| Live promote | **Forbidden** for AI bypass outputs |
| Entry hard-bind | **Forbidden** (`hard_bind_entry=false`) |
| Output path | validation report / ModelRegistry **paper** path only |
| Default | pipelines remain **OFF** until operator enables |

## Offline job sketch

```bash
set PYTHONUTF8=1
# Focused unit lock (always green before offline jobs)
python -m pytest tests/unit/test_ai_validation_bypass.py tests/unit/test_rd_agent.py -q

# CLI / module entry (see t036 doc for exact flags in tree)
# python -m quantflow ... ai-bypass / scripts that call run_ai_validation_bypass
```

Core module: `quantflow/strategy/ai_validation_bypass.py`  
- stamps research provenance  
- asserts no live promote path  

## Operator checklist

1. Confirm no live API keys required for the job (offline / paper data).
2. Run bypass → inspect validation stamps / decision.
3. If interesting: open a **new research contract ID** (do not edit B0/B3–B5 freezes).
4. Dual-path / CPCV / Path B OOS still required before any paper_evidence narrative.
5. T023/T024 ops remain independent — AI factors do not skip sample floors.

## See also

- [iss-006-pipeline-audit.md](../research/iss-006-pipeline-audit.md)
- [DOC-20260811-learnings-params-structure.md](../../.workflow/knowhow/DOC-20260811-learnings-params-structure.md)
- IMP residual plan § optional 06–09
