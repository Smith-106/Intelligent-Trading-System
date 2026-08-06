---
title: ModelRegistry 模型注册设计：GO 状态持久化 + path 遍历防护
category: ai
createdBy: "harvest:wave2-s3"
sourceRef: maestro-wave2-s3-20260803-20260804-040400
---
# ModelRegistry 模型注册设计

## 适用场景
AI 模型训练完成后，需要注册到运行时系统。注册过程需状态持久化、防护恶意路径、gate 决定是否启用。

## 设计要点

1. **GO 状态持久化**：非 GO 状态 → status=rejected 持久化（记录失败原因，便于审计）
2. **path 遍历防护**：`ModelRegistry._path` 拒绝 `/`, `\`, `..` 字符（路径遍历测试 `../evil` 确认拒绝）
3. **gate 决策**：读取 `data/ai_reports/{id}.json`，gate 决定 paper vs rejected
4. **CLI 集成**：通过 `quantflow ai register <id>` 触发注册流程

## 安全设计
- 路径遍历防护：白名单字符集，拒绝目录穿越
- 状态持久化：所有注册结果（含拒绝）写入 JSON，可追溯
- 退化路径：CLI 缺失/无 key/超时/异常 → Alpha158 基线 + warning

## 来源
maestro-wave2-s3 session (2026-08-04), review-findings.json R-F5..R-F7