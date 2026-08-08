---
title: "Review Standards"
readMode: required
priority: medium
category: review
keywords:
  - review
  - checklist
  - gate
  - approval
  - standard
---

# Review Standards

## Entries

<spec-entry category="review" keywords="csrf,layered-controls,early-return,origin,x-requested-with" date="2026-07-05" title="Layered security controls must all execute — no early-return past a passing control" description="Auth+CSRF middleware must run both controls per request; same-origin signal is Origin only, never X-Requested-With" sid="S-legacy-abe97254">
### Layered security controls must all execute — no early-return past a passing control

Security middleware that claims "layered defense-in-depth" (e.g. auth + CSRF) must run ALL controls to completion per request — a `return` after one passing control makes the others dead code. Two concrete rules:

1. A `return await handler(request)` is only permitted after a control REJECTS the request, never after it passes. A valid token must NOT short-circuit the CSRF check — the controls are orthogonal (auth = who, CSRF = browser intent).
2. The same-origin signal must be browser-unforgeable (the `Origin` header). NEVER accept an attacker-controllable header like `X-Requested-With` — it is NOT a forbidden CORS header, so any cross-origin `fetch()` can set it, making it a CSRF bypass.

Closing pattern: `quantflow/web/security.py` `same_origin_guard` — the token auth check falls through to the CSRF Origin check (no early return on valid token), and `X-Requested-With` is not consulted. The `Host` header is used only as the address a browser guarantees matches the actual server (a non-browser client can forge Host, so it is not trusted as the reference address alone).

Test proof: `test_valid_token_does_not_skip_csrf_for_cross_origin` (valid token + mismatched Origin → 403) and `test_cross_origin_mutation_blocked_even_with_custom_header` (cross-origin POST with `X-Requested-With: XMLHttpRequest` → 403).

Source: odyssey-review security-fixes session (REV-001, REV-002).
</spec-entry>


<spec-entry category="review" keywords="仓位绑定,vol-target,es_97.5,fat-tail,半kelly" date="2026-07-18" sid="S-20260718-c3vv" title="仓位绑定规则取三者下界 + ES_97.5 主风险指标 + fat-tail 警示" description="仓位取 min(half-Kelly,vol-target,单名上限);ES_97.5 主指标,parametric VaR 降级" source="harvest:deep-research-20260718">

### 仓位绑定规则取三者下界 + ES_97.5 主风险指标 + fat-tail 警示

风控叠加层绑定规则应为仓位 = min(half-Kelly, vol-target, 单名上限):纯 Kelly 几乎总是过度加仓,半 Kelly 是默认,但缺 vol-target 会在低波动期过度加仓,必须补 vol-targeting 第三件套。VaR 不应用 parametric-normal(Gaussian)——crypto 收益尖峰厚尾会系统性低估肥尾,应将 ES_97.5(Expected Shortfall, FRTB 自 2019 起替代 99% VaR 的相干风险度量)提升为主指标,parametric VaR 降级为辅助,并保留 fat-tail 警示。这是 Hull/McNeil-Frey-Embrechts/Basel FRTB 一致结论。注: 来源推荐的具体阈值(10%单名/40% top-3/3x杠杆)已被 deep-research 0-3 否决(来源自相矛盾+非权威),不可作为硬规则,仅 vol-target/ES 机制本身成立。来源: deep-research-20260718 F3/F4 (3-0 verified)。

</spec-entry>

<spec-entry category="review" keywords="ccxt,reduceOnly,camelCase,参数命名,跨交易所" date="2026-07-22" sid="S-20260722-z4dr" title="CCXT 交易所统一参数用 camelCase — verify against canonical docs not Python convention" description="reduceOnly 是 CCXT 跨交易所统一约定(camelCase)；snake_case reduce_only 可能被实盘网关静默忽略，校验时按 CCXT 官方文档而非 Python 命名惯例" source="harvest:p1-parity-paths-20260720">

### CCXT 交易所统一参数用 camelCase — verify against canonical docs not Python convention

CCXT 作为统一交易所抽象层，其  等方法的参数名遵循 CCXT 自身的 camelCase 约定（如 、、），而非各交易所原生 API 的 snake_case。QuantFlow 各 Gateway（OKX/Paper）向 CCXT 传参时 MUST 使用 CCXT canonical camelCase 名。若误用 Python 惯例的 snake_case（），CCXT 的 unified API 会将其视为未知参数而**静默忽略**——订单以非 reduce 方式发出，在实盘对冲/平仓路径上产生与回测不一致的持仓累积，破坏 backtest/live parity。

校验规则：凡 CCXT 网关层参数，对照 CCXT 官方文档（ccxt.com/manual）的 unified API 字段名核对，而非按 Python 命名惯例臆测。 这类布尔参数尤其危险——它在 hedge/derivatives 路径上决定是否开新仓还是减仓，静默失效即等于「本应平仓却开仓」。

发现来源：odyssey-review p1-parity-paths session (SEC dimension inline lesson)——零残留 review 捕到  注释/值不一致。该 finding 未单独成 spec，本次 harvest 收割固化。
</spec-entry>


<spec-entry category="review" keywords="redaction,choke-point,cwe-532,credential,security" date="2026-07-24" sid="S-20260724-9smk" title="credential 异常 choke point 静态守护" description="凭证路径异常必须过 redact_secrets；静态 guard 守护 choke point 防 raw-log 回归" source="main@bb3c6cd">

### credential 异常 choke point 静态守护

凭证路径模块（kill_switch/execution-engine/strategy-engine/cli/alerts/okx-gateway）的 exception str 必须经 redact_secrets(str(e)) 或 _safe_error 再 log/print/response。gateway 自己 scrub 日志但 re-raise raw CCXT 异常时，下游 caller（kill_switch results['errors']->web json_response HTTP response、engine logger、cli print）是 unguarded sink——OKX apiKey/URL 会泄漏到 log + HTTP response。静态 guard test_credential_bearing_modules_have_redaction_choke_point 扫源码确认这些模块引用 redact_secrets 或 _safe_error，防未来 raw-log 回归。root cause 不是单 sink 而是 choke point 缺失，修复必须 gate 在 choke point（每消费 sink scrub，不只 gateway 内部）。

</spec-entry>