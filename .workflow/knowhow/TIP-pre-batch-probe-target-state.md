---
title: "Pre-batch probe target state"
type: tip
tags: [workflow, verification]
status: active
related:
  - DOC-knowledge-hub
---
---
related:
  - "spec:project:learnings-012"
---
# TIP — scoping fix batch 前先 probe 目标状态

- **Source**: retrospective security-hardening-20260722 (process lens)
- **INS-id**: INS-7b17e05e
- **Confidence**: medium

Batch F 发现 feature_store SQL 已参数化并 pivot 到 JSONL——happy outcome，但发现在执行而非规划时。2 分钟 pre-batch probe（grep target SQL surface 的 f-string/format）会在任何工作开始前 re-scope batch F。不专注的执行可能产出重复参数化。把 pre-batch 目标态验证作为规划步骤而非执行时发现。

证据: quantflow/data/feature_store.py:96, commit 8d4e609
