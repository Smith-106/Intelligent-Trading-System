---
title: LLM 端点验证三要素模式：endpoint/key/model triple 验证 + 凭证安全审计
category: ai
createdBy: "harvest:smoke-llm"
sourceRef: maestro-smoke-llm-20260804-20260804-065343
type: knowhow
status: active
---
# LLM 端点验证三要素模式

## 适用场景
集成 LLM 端点时，需要系统性验证连通性、凭证安全性和退化路径。

## 三要素验证

1. **Endpoint 可达**：HTTP 200 + model echo（确认端点返回预期模型名）
2. **Key 有效**：usage tokens 非零（确认 API key 有配额）
3. **Env wiring 正确**：3/3 assertions（env 三要素齐全 / 无 key 时 None 降级 / config 优先级覆盖）

## 凭证安全审计
- API key 通过 process env 传递，脚本只读 env 不硬编码
- 请求体 = 最小化 ping（无敏感 payload）
- 错误体截断 300 字符后打印
- 零 key 明文写入文件（S4 证据：全量 scan 零命中）

## 退化路径验证
- CLI 缺失 → fail-fast + install hint（exit 0，无 traceback）
- 无 key → None 降级触发
- 超时/异常 → Alpha158 基线 + warning

## 来源
maestro-smoke-llm session (2026-08-04), review-findings.json R-F1..R-F7