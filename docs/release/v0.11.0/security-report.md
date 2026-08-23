# v0.11.0 安全报告

本版包含两轮共识式安全审计的修复（REV-010 web 入口基线 + SEC-REV020 复审）。

## 高危修复
| 发现 | 修复 | 验证 |
|------|------|------|
| X-Forwarded-For 无条件采信 → 限频桶键伪造绕过 | 仅白名单代理可设置 XFF；桶键折叠凭据摘要 | 不变量测试 + 定向回归 |
| 同源策略缺口（无 token + 非 loopback + 无 Origin） | 一律 403 | 策略矩阵测试 |
| 对账审计 HMAC 密钥硬编码（test-only 字样入库） | 外置 QUANTFLOW_AUDIT_HMAC_KEY，缺省 fail-open-with-warning | 配置审计 |

## 中低危修复
- CSP 强化（frame-ancestors 'none' + 显式 src 白名单 + Permissions-Policy）
- 未知 API 404 不回显请求路径；策略 id 错误码 500→400
- 日志三层脱敏边界统一推进：redis 连接串密码、reconciliation 异常体、rdagent 子进程环境变量白名单
- default.yaml 移除 ${TELEGRAM_BOT_TOKEN} 插值示例（防真实凭证误入版本库）

## 遗留与建议
- mypy strict 存量违规未清（历史堆积，非安全项）
- structlog _redact_processor 不遍历嵌套载荷（护栏缺口，当前无实际穿透路径，已记录）
