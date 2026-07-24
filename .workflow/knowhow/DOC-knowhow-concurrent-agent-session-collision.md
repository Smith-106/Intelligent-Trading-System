---
title: 并发 Agent 会话并行提交同仓 — ancestry 检查 + 工作区审计防冲突
category: arch
createdBy: manage-harvest
sourceRef: "session:20260724-debug-odyssey-l6-sibling-sinks, commit:b2a4cf8"
---
# 并发 Agent 会话并行提交同仓 — ancestry 检查 + 工作区审计防冲突

## 场景

单个仓库被多个 agent 会话（如 odyssey-debug + 并行 maestro-cli 会话）同时操作时，
会出现：A 会话基于 commit X 开始工作，期间 B 会话提交了 X→Y（含 A 未触及的文件），
A 提交时基于 Y（fast-forward）或产生交叉。更隐蔽的是：A 会话工作区里出现 B 会话
"in-flight" 的未提交改动（B 正在写的文件），A 若不审计就提交会混入 B 的工作。

## 本会话实例 (2026-07-24 l6-sibling-sinks)

odyssey-debug 修复 ISS-044（3 sibling L6 耦合站点）期间，工作区出现
`paper_gateway.py` + `test_execution.py` 的未提交改动（ISS-021 reduceOnly parity）。
排查发现是并行 maestro-cli 会话的 in-flight 工作——它随后自己提交了
`7aa7139`(ISS-021) / `cc72b9e`(ISS-022) / `a634758`(ISS-019-RECORD) 并关闭了
ISS-019/021/022/044。本会话的 `b2a4cf8`(ISS-044 fix) 基于 `7aa7139` 之上（无冲突，
因为不触及 paper_gateway）。

## 检测信号

- 工作区出现**自己没编辑过**的文件改动（`git diff` 显示陌生文件）
- `git log` 出现**自己没做**的 commit（author/timeframe 不符）
- issue 在 `issue-history.jsonl` 里被**别的 actor**（如 `maestro-cli`）关闭
- `git diff --stat` 行数在两次检查间**无故变化**（并发会话提交/回退了文件）

## 防护模式

1. **提交前 ancestry 检查**：`git merge-base --is-ancestor <other-commit> HEAD`
   确认自己的 commit 基于并发会话的最新提交之上（无分叉冲突）。
2. **工作区审计**：`git status` / `git diff --stat` 检查是否有陌生文件改动；
   只 `git add` 自己本次逻辑相关的文件，**绝不** `git add -A` 混入并发会话的 in-flight 工作。
3. **issue 状态复核**：关闭 issue 前检查 `issue-history.jsonl` 是否已被并发 actor 关闭，
   避免重复关闭/覆盖。
4. **push 前重读**：网络重置等导致 push 失败重试时，重新 `git fetch` + 比对 ahead/behind，
   确认远程状态未在失败窗口期被并发会话推进。

## 工具陷阱叠加

本场景叠加了 "Grep-after-Edit 缓存滞后"（learnings INS-ca90827c）：Grep 工具返回
陈旧索引，一度误判 `execution/engine.py` 改动丢失——实际是磁盘正确、Grep 缓存滞后。
并发会话 + 工具缓存滞后双重干扰下，**python open() / Read 直接读磁盘**是唯一可靠交叉验证。

## 适用范围

多 agent 并行操作同一 git 仓库的任何工作流（odyssey-* 系列、maestro delegate write 模式、
CI bot + 本地开发并发）。单 agent 串行工作流不适用。
