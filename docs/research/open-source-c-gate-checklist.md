# Open-source scheme **C** gate checklist (T020)

> **Status**: Engineering readiness checklist — **not** an approval to go public.  
> **Visibility**: Never flipped by automation. Human-only.  
> **Current published path**: Scheme **B** (docs-demo public). Scheme **C** = optional future.

Related: [open-source-decision-brief.md](./open-source-decision-brief.md) · `python scripts/oss_c_gate.py` · `CONTRIBUTING.md`

## 0. Decision posture

| Item | Required answer before C |
|------|---------------------------|
| Why C (not stay on B)? | Written in decision brief §6 update |
| Accept PR/issue load? | Yes / No |
| Core LICENSE | MIT (root today) vs Apache-2.0 — **pick one** |
| Research artifacts policy | Real `gate.json` / full-window PnL **stay private** by default |
| Success metric | **Not** stars; cost-aware paper-first OS |

## 1. Automated local gate

```bash
python scripts/oss_c_gate.py          # full
python scripts/oss_c_gate.py --json   # machine-readable
python scripts/oss_c_gate.py --quick  # skip demo pack I/O
```

Must report `ready_for_human_c_review=true` (exit 0).

| Check | What it proves |
|-------|----------------|
| docs | CONTRIBUTING, LICENSE, decision brief, this checklist, PUBLISH.md |
| gitignore | `.env`, `*.key` (and recommends `data/`) |
| secrets | Heuristic tree scan (not full git history) |
| demo_pack | `docs/demo` no-secret pack still valid |
| ci | Root CI exists; optional `oss-c-gate.yml` present |

## 2. Manual / history (automation cannot skip)

- [ ] **gitleaks** (or trufflehog) on **full git history**; rotate any live keys.
- [ ] Confirm no private paper sessions / full-window cost JSON force-added.
- [ ] README still leads with positioning + Path A/B + non-goals.
- [ ] `default.yaml` `portfolio_optimization.enabled=false` unchanged unless intentional.
- [ ] Public CI plan: `pytest -m "not live"`, ruff, `demo_public_pack.py --check`, `oss_c_gate.py --quick`.
- [ ] Issue templates optional; security contact path defined.

## 3. CI suggestion (path C)

Workflow file (optional, already in repo for dispatch):

`.github/workflows/oss-c-gate.yml`

Recommended jobs if C is approved:

1. Existing `ci.yml` quality job (ruff / mypy / pytest).
2. `python scripts/oss_c_gate.py --quick`.
3. `python scripts/demo_public_pack.py --check`.
4. (Optional) gitleaks-action on PRs — **enable only after path C**.

Do **not** make “publish visibility” a CI step.

## 4. Publish sequence (human)

1. Pass §1–§2.  
2. Record decision in open-source brief (date, LICENSE, scope).  
3. Tag release; ensure `data/` and secrets remain untracked.  
4. GitHub **Settings → Danger zone → visibility** only after 1–3.  
5. Announce: paper-first OS; demo docs remain the no-key entry.

## 5. Explicit non-actions for agents

- Do not run `gh repo edit --visibility public`.
- Do not force-add `data/paper_replay/**` research dumps.
- Do not weaken cost_fidelity / funding_tca / paper_readiness for “easier OSS”.

## 6. T020 done criteria (engineering)

- [x] CONTRIBUTING.md
- [x] `scripts/oss_c_gate.py` + unit tests
- [x] This checklist
- [x] Optional CI workflow `oss-c-gate.yml`
- [x] Decision brief pointer updated
- [ ] **Human** C go/no-go (out of band)
