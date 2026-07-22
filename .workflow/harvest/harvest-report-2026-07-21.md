# Harvest Report — 2026-07-21

## Source
7 artifacts harvested (近 30 天未收割 session):
- 20260704-review-odyssey-deepfix (review, 52 findings)
- 20260705-debug-odyssey-ci-ruff-breakage (debug)
- 20260705-debug-odyssey-position-sizing-regression (debug)
- 20260705-review-odyssey-security-fixes (review, 14 findings)
- 20260705-security-audit-deep-quantflow (scratchpad, 24 findings)
- 20260705-security-audit-deep-quantflow-verify (scratchpad)
- 20260720-review-odyssey-p1-parity-paths (review, 30 findings)

## Extraction Summary
- Fragments found: 22 (raw, issue-gradable)
- Filtered by confidence >= 0.6: 22 kept
- Spec fragments: 22 SKIP-DUP (all patterns already in S_RECORD-added specs)
- Wiki fragments: 0 (no new generalizable insight beyond existing specs/knowhow)
- Duplicates skipped (spec/wiki): ~30 (8 deepfix patterns + security G1-G5 + P1 PAT-001 all pre-existing)
- Consolidated 22 raw → 12 issue (by theme)

## Routing Results

### Wiki (0 entries)
All insights already persisted as spec/knowhow in prior S_RECORD passes.

### Spec (0 entries — all SKIP-DUP)
Existing specs already cover the patterns:
- coding-conventions: 策略双模式 / validate_symbol-every-site / ruff-before-commit / no-look-ahead-vectorized / 大规模参数扫描 / compound-strategy_id
- architecture-constraints: generate_signals 研究 API / 新增策略实施顺序 / W3 铁律 / divergence 浪级 / ScalingPosition 权限 / 波浪集成 / security-primitives-public / launch-guard-bind-boundary / LLM 因子 schema-only / parity 范式 / 跨交易所套利候选
- debug-notes: E712-bool / YAML-pydantic-schema-drift
- review-standards: layered-controls-no-early-return / 仓位三下界+ES97.5

### Issue (12 entries)
| # | Severity | Title | ID | Source |
|---|----------|-------|-----|--------|
| 1 | medium | Web endpoint DoS 面:无 rate limiting + 无 POST body size cap (SEC-006+007) | ISS-20260721-001 | 20260705-security-audit-deep-quantflow |
| 2 | medium | Secret redaction 不完整:漏 Telegram/LINE/Redis + last_error fallback 绕过 (SEC-008+009) | ISS-20260721-002 | 20260705-security-audit-deep-quantflow |
| 3 | medium | AlertManager webhook SSRF sink:无 scheme allowlist + 无 IP blocklist (SEC-010) | ISS-20260721-003 | 20260705-security-audit-deep-quantflow |
| 4 | medium | Verbose exception 回显客户端:7 个 handler 返回 str(exc) (SEC-011) | ISS-20260721-004 | 20260705-security-audit-deep-quantflow |
| 5 | medium | Docker hardening:Dockerfile root + Redis 暴露无 auth + Grafana admin/admin (SEC-012+013) | ISS-20260721-005 | 20260705-security-audit-deep-quantflow |
| 6 | low | 部署 hardening:.gitignore 漏私钥 + 无 TLS + host guardrail (SEC-015+016+017) | ISS-20260721-006 | 20260705-security-audit-deep-quantflow |
| 7 | low | Exec/logging 卫生:config_path footgun + OKX 日志含原始 exc (SEC-019+020) | ISS-20260721-007 | 20260705-security-audit-deep-quantflow |
| 8 | low | Session 安全:无暴力破解保护/会话过期 + 可预测 session_id (SEC-021+022) | ISS-20260721-008 | 20260705-security-audit-deep-quantflow |
| 9 | low | CI/供应链卫生:SQL f-string + JSONL schema + 浮动 action tag + :latest 镜像 (SEC-005+018+023+024) | ISS-20260721-009 | 20260705-security-audit-deep-quantflow |
| 10 | medium | catalog.py 硬编码 titles/descriptions/param_space 应移至 YAML (deepfix I8) | ISS-20260721-010 | 20260704-review-odyssey-deepfix |
| 11 | medium | CLI benchmark ~400 行直接编排 ExecutionEngine 应抽 service (deepfix I10) | ISS-20260721-011 | 20260704-review-odyssey-deepfix |
| 12 | medium | paper_gateway/position_sizer 硬编码 fallback 未 config-sourced (deepfix I12+I13) | ISS-20260721-012 | 20260704-review-odyssey-deepfix |

## Skipped (duplicates)
| Fragment class | Reason |
|----------------|--------|
| deepfix 8 generalization patterns | 已在各 session S_RECORD 阶段 /spec-add 落 coding+arch+debug |
| security G1-G5 patterns | 已在 20260705-review-odyssey-security-fixes S_RECORD 落 arch+review+debug |
| P1 parity PAT-001 compound-key | S-20260720-98vs 已落 coding (ISS-004 跟踪) |
| ruff-before-commit / E712 | deepfix+ci-ruff session S_RECORD 已落 coding+debug |
| position-sizing YAML-drift | position-sizing-debug S_RECORD 已落 debug |
| 现有 ISS-20260720-003/004/005/006 | #9 review 已建,本会话已更新 ISS-003/004,不重复 |

## Notes
- 本次 harvest 最大价值:security audit (scratchpad) 的 medium/low 未修项首次落 issue store
  (原 audit 仅 findings.md,未 /manage-issue create)。
- deepfix I1-I7/I9/I11/I14/I15 已被 ISS-20260720-005/006 或既有修复覆盖,仅 I8/I10/I12/I13 独立登记。
- 建议后续 hardening pass 集中处理 ISS-20260721-001..009 (security cluster)。
