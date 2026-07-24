---
title: "Learnings"
readMode: optional
priority: medium
category: learning
keywords:
  - bug
  - lesson
  - gotcha
  - learning
---

# Learnings

Add entries with: `/spec-add learning <description>`

## Entries

<spec-entry category="pattern" keywords="security,common-layer,single-source-of-truth,g2-standard" date="2026-07-22" id="INS-ed9b4bab" source="retrospective">

### 跨层安全控制提升为 common/ 公共 API + 薄 backcompat wrapper（单一审计面）

当安全原语（redaction/SSRF guard/symbol validation）被 >1 层引用时，提升到 quantflow/common/ 为公共 API（无下划线），原私有位置留一行委托 wrapper 做 backcompat。给出单一审计面 + 单一扩展点；新集成只需往 tuple 加一个 env 名而非新 scrubber。rejected alternative: private _helper 跨模块 borrow-in（G2 antipattern）。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: technical
- **Confidence**: high
- **Evidence**: ['quantflow/common/redaction.py:25', 'quantflow/web/session_manager.py:94', 'quantflow/common/url_safety.py:21', '84f1545', '87bfa51']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="pattern" keywords="security,regression-guard,static-test,ci" date="2026-07-22" id="INS-6063364e" source="retrospective">

### 每个 hardening 修复冻结为静态 grep guard 测试（footgun 按名无法静默回归）

关闭安全 issue 后，加一个 grep 相关文件集的 antipattern 签名测试（web 层 resolve_config_path(、compose :latest、workflow 浮动 @vN）。CI 时跑，捕获未来按名重新引入 footgun 的 commit，先于 path-traversal/supply-chain 回归上线。优于会腐烂的 prose review-checklist。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: technical
- **Confidence**: high
- **Evidence**: ['tests/unit/test_web_config_path_guard.py:29', 'tests/unit/test_deployment_hardening.py:14', 'tests/unit/test_deployment_hardening.py:55', '6570814', '548a229']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="pattern" keywords="security,defense-in-depth,layer-choke-point,validation" date="2026-07-22" id="INS-686f55ec" source="retrospective">

### 每个层边界都校验不可信输入（web edge pydantic + gateway symbol + 持久化 category 白名单）

每层用自身关注点重新校验（web: shape/depth/size；execution: symbol 格式在 create_order 前；persistence: category 白名单在 path join 前）。若未来内部 caller 绕过 web edge（CLI/test/event 路径）直达 gateway/store，冗余校验兜底。防御在任一层被削弱后仍存活。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: technical
- **Confidence**: high
- **Evidence**: ['quantflow/web/service.py:90', 'quantflow/execution/okx_gateway.py:106', 'quantflow/web/history.py:148', 'a3d5513', '6570814', '8d4e609']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="pattern" keywords="security,supply-chain,docker,ci,sha-pin" date="2026-07-22" id="INS-8eaddcfd" source="retrospective">

### 第三方镜像钉主版本 tag + GitHub Actions 钉 SHA@comment，禁用 :latest / 浮动 @vN

浮动 tag 让上游 supply-chain push 静默改变生产运行物。镜像钉具体版本（redis:7-alpine, grafana/grafana:11.5.2），actions 钉 name@<40-hex-sha> # vN。加静态 guard 让未来 :latest / 浮动 @vN 在 CI 被拒。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: technical
- **Confidence**: high
- **Evidence**: ['docker/docker-compose.yaml:55', '.github/workflows/ci.yml:23', 'tests/unit/test_deployment_hardening.py:55', '548a229']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="arch" keywords="security,threat-model,right-sizing,arch" date="2026-07-22" id="INS-2a662598" source="retrospective">

### 控制前先声明威胁模型，让模型决定控制强度

single-operator local-first 模型（loopback bind + 可选 shared-secret token）在 rate limiter docstring 显式命名，用于论证保守 bucket size、GET 豁免、DNS-deferred SSRF 检查。命名威胁模型防止 over-engineer 公网 rate limiter，让 GET-exempt + light-DoS-brake 设计自证。模型隐式时控制漂向 under-protection 或 gold-plating。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: decision
- **Confidence**: high
- **Evidence**: ['quantflow/web/rate_limit.py:13', 'quantflow/common/url_safety.py:43', '548a229']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="antipattern" keywords="security,observability,diagnostics,tradeoff" date="2026-07-22" id="INS-8019d094" source="retrospective">

### 勿只记录 redacted exception 给服务端日志——保留 raw diagnostics 通道否则丢事故后可复现性

单一 error-response sink 跑 redact_secrets(str(exc)) 后 log redacted 字符串，对 client 安全但摧毁 server log 的 raw CCXT/DuckDB error body。当 redaction 可能剥掉 load-bearing detail（OKX error code/path/query）时，DEBUG 级或 operator-only sink 记全 exception，client/INFO 仅记 redacted 形态。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: technical
- **Confidence**: medium
- **Evidence**: ['quantflow/web/app.py:74', '84f1545']
- **Routed to**: issue (—)

</spec-entry>


<spec-entry category="gotcha" keywords="security,redaction,regex-drift,test-coverage" date="2026-07-22" id="INS-741da4eb" source="retrospective">

### shape-based redaction regex 是维护型 allowlist 不是一次性修复——配 coverage 测试喂已知格式 secret

bot-token/Bearer regex 锚定特定 provider 当前 token 格式（Telegram {digits}:{30+ base64url}）。格式漂移或新 alert channel 静默禁用 scrubbing。加测试构造 expected shape 的合成 token 并断言被 scrub（env 未设时也行）；每加 secret-bearing 集成时复查。另缺 near-miss/benign-collision 对抗测试。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: technical
- **Confidence**: medium
- **Evidence**: ['quantflow/common/redaction.py:49', 'quantflow/common/redaction.py:54', 'tests/unit/test_redaction.py', '84f1545']
- **Routed to**: issue (—)

</spec-entry>


<spec-entry category="quality" keywords="test-coverage,security,residual-risk,static-guard" date="2026-07-22" id="INS-bec2fd56" source="retrospective">

### 残余风险路径需 pinned 测试，不能只 docstring 让步

当 guard 显式 scope out 一个风险（XFF trust、DNS rebinding、static-guard 自校验）且 docstring 让步时，缺一个编码该残余的测试 = 该 gap 对未来 reviewer 不可见且静默扩大。为每个让步残余 pin 一个 negative test 或 known-gap marker test。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: quality
- **Confidence**: high
- **Evidence**: ['quantflow/web/rate_limit.py:_client_key', 'quantflow/common/url_safety.py:70', 'tests/unit/test_web_config_path_guard.py', 'tests/unit/test_deployment_hardening.py']
- **Routed to**: issue (—)

</spec-entry>


<spec-entry category="pattern" keywords="quality-gate,mypy,pre-commit,test-vs-type" date="2026-07-22" id="INS-7b99803f" source="retrospective">

### fix-time test-pass ≠ type-pass；mypy --strict 纳入 per-batch pre-commit gate

Batch E 提交 9e49629 声称零回归，27 分钟后需单独 f966b30 满足 mypy strict（nullable operator_id 断言）。per-batch gate 跑了 pytest 但没跑 mypy --strict，type friction 在 fix 落地后才浮现。把 mypy --strict 与 ruff + pytest 一起纳入 per-batch pre-commit gate，消除 post-fix type-fixup loop。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: process
- **Confidence**: high
- **Evidence**: ['9e49629', 'f966b30', 'tests/unit/test_session_security.py:65']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="pattern" keywords="wave-planning,scope-decomposition,cross-layer" date="2026-07-22" id="INS-3d282fd2" source="retrospective">

### 跨层 issue 按 layer 拆分而非按 issue 整体

ISS-009 跨 data-layer(JSONL) + infra-layer(Docker/CI)，被迫 mid-pass 拆 batch F/G。单 issue 触多层时，pre-decompose 成对齐 wave plan 的 per-layer sub-task，而非执行中发现拆分。避免 mid-wave re-scope 和残留 surface 风险。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: process
- **Confidence**: medium
- **Evidence**: ['8d4e609', '548a229']
- **Routed to**: spec (—)

</spec-entry>


<spec-entry category="debug" keywords="process,audit-drift,work-item-validation,backlog-hygiene" date="2026-07-22" id="INS-88f77d33" source="retrospective">

### 排程 work item 前先验证 finding 仍可复现——audit→issue 管道会漂离 code 现实

ISS-20260721-009 从 2026-07-05 安全审计创建，声称 feature_store SQL 用 f-string 插值，但 fix 时（07-21）code 已用 ? placeholder——工作已做完。pivot 到 JSONL 挽回了 effort，但 audit→issue 路径无 still-reproducible gate。issue 创建时加 re-verification 步骤可避免给已满足工作分配 batch。stale finding 消耗 sprint capacity 并侵蚀 backlog 信任。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: decision
- **Confidence**: medium
- **Evidence**: ['ISS-20260721-009 description vs resolution', 'quantflow/data/feature_store.py:95', 'ISS-20260721-009 issue_history']
- **Routed to**: issue (—)

</spec-entry>


<spec-entry category="technique" keywords="rework-prevention,pre-batch-probe,scope-verification" date="2026-07-22" id="INS-7b17e05e" source="retrospective">

### scoping fix batch 前先 probe 目标状态

Batch F 发现 feature_store SQL 已参数化并 pivot 到 JSONL——happy outcome，但发现在执行而非规划时。2 分钟 pre-batch probe（grep target SQL surface 的 f-string/format）会在任何工作开始前 re-scope batch F。不专注的执行可能产出重复参数化。把 pre-batch 目标态验证作为规划步骤而非执行时发现。

- **Phase**: 0 (security-hardening-20260722)
- **Lens**: process
- **Confidence**: medium
- **Evidence**: ['quantflow/data/feature_store.py:96', '8d4e609']
- **Routed to**: note (—)

</spec-entry>

<spec-entry category="technique" keywords="grep-cache,tool-lag,edit-verification,python-open" date="2026-07-24" id="INS-ca90827c" source="odyssey-debug">

### Grep 工具在 Edit 后返回陈旧缓存——用 python open()/Read 交叉验证

ISS-20260724-044 修复期间（execution/engine.py 移除 ORDER_LATENCY import + 4 call sites 改 self._sink），Edit 工具调用全部报告成功，但随后 `grep` 命令仍返回**旧内容**（显示 line 25 还有 `from quantflow.monitoring.metrics import ORDER_LATENCY`、line 152/196 仍是 `ORDERS_TOTAL.labels(...)`）——一度误判 Edit 未持久化、文件被回退。用 `python -c "open(file).read()"` 或 Read 工具直接读磁盘，确认实际状态正确（改动全在）。

**Why:** Grep 工具基于 ripgrep 索引，Edit 写入磁盘后索引未即时刷新（Grep-after-Edit cache lag）。这不是代码问题、不是文件回退——是工具索引滞后。本会话遇到 2 次（execution/engine.py 中途 + risk_engine.py generalize 扫描），各浪费一次排查。

**How to apply:** 当一次 Grep 结果与刚应用的 Edit 矛盾时，**不要立即重做 Edit 或 panic**。先用 `python -c "f=open(p,encoding='utf-8').read(); [print(i,l) for i,l in enumerate(f.splitlines(),1) if '<pattern>' in l]"` 或 Read 工具直接读磁盘交叉验证。磁盘读对工具索引缓存免疫。只在 python-read 也确认旧内容时，才认为 Edit 真的失败/被回退。

- **Phase**: ISS-20260724-044 (l6-sibling-sinks)
- **Lens**: tooling
- **Confidence**: high
- **Evidence**: ['quantflow/execution/engine.py:17,45,159,272', 'b2a4cf8']
- **Routed to**: note (—)

</spec-entry>


<spec-entry category="learning" keywords="metrics-server,幂等,测试顺序依赖,端口状态隔离" date="2026-07-24" sid="S-20260724-3jyz" title="幂等状态下沉到模块全局致测试顺序依赖 — 测试须显式重置全局" description="把去重状态从调用方 set 下沉到模块级全局字典后，断言该状态从'未尝试'开始的测试变成顺序依赖 flaky，须显式 pop 重置">

### 幂等状态下沉到模块全局致测试顺序依赖 — 测试须显式重置全局

`start_metrics_server` 改为 per-port 幂等后（ISS-019，commit 1bf8e2b），`test_metrics_extra::test_start_metrics_server` 变成顺序依赖 flaky：若先前测试已把该 port 标记为 attempted（`_METRICS_SERVER_STATE[port]["attempted"]=True`），则 mock `start_http_server` 后该 port 的调用会 no-op 返回，断言 "called once" 失败（Called 0 times）。修复：测试开头 `metrics._METRICS_SERVER_STATE.pop(port, None)` 隔离端口状态。

根因：幂等性把"是否已尝试"状态从调用方（engine 的 `_ATTEMPTED_METRICS_PORTS` set，每实例/测试独立）下沉到 metrics 模块全局字典（跨测试共享）。ISS-044 同型 sink 路径沿用同一 `start_metrics_server`。

**教训**：把去重/缓存状态下沉到模块级全局时，任何断言该状态从"未尝试/空"开始的测试必须显式重置该全局（pop/clear），否则受测试执行顺序污染。这是"状态下沉"重构的固有测试代价——检测：grep 测试里 `assert_called_once` + 被测函数有模块级状态字典 → 加 pop 隔离。

</spec-entry>
