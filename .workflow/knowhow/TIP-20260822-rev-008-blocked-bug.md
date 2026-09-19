---
title: "REV-008: 全部 BLOCKED 可能是探测路径 bug 而非门禁生效"
type: tip
created: 2026-08-22T08:25:00.775Z
appliesToRepoIds:
  - 4df0e1f8-a4e6-4872-8eb3-857aef7909ed
summary: 背景：odyssey REV-008 修复 archive_legacy_partitions 时，最初把全部 BLOCKED 解读为覆盖度门正确拦截。 教训：候选分区探测用原始斜杠形式（BTC/USDT-OKX）拼路径永不命中，所有真实候选被静默跳过——BLOCKED 是 bug 不是门禁工作。修复（validate_symbol 规范化）后覆盖度门才第一次真正生效。任何'防御机制拦截了一切'的观察都要先验证机制本身是否在跑真路径。
lifecycleStatus: active
related:
  - knowhow-doc-knowledge-hub
---

背景：odyssey REV-008 修复 archive_legacy_partitions 时，最初把全部 BLOCKED 解读为覆盖度门正确拦截。
教训：候选分区探测用原始斜杠形式（BTC/USDT-OKX）拼路径永不命中，所有真实候选被静默跳过——BLOCKED 是 bug 不是门禁工作。修复（validate_symbol 规范化）后覆盖度门才第一次真正生效。任何'防御机制拦截了一切'的观察都要先验证机制本身是否在跑真路径。
