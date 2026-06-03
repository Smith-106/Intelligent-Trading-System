# QuantFlow v0.1.0 Security Report

发布日期：2026-06-03

## 范围说明

本报告覆盖当前仓库内可直接验证的安全项，不虚构外部 SaaS 扫描结果。

验证范围：

- 源码中是否存在明显硬编码敏感信息。
- 配置保存是否对敏感字段做脱敏。
- 实盘凭证是否要求从环境变量注入。
- 发布包是否避免内置 `.env` 等开发期敏感文件。

## 本地检查结果

### 1. 硬编码敏感信息检查

已对 `quantflow`、`tests`、`scripts`、`README.md`、`pyproject.toml`、`docker` 做关键字扫描。

结论：

- 代码中未发现可判定为真实生产密钥的硬编码值。
- 命中项主要为配置字段名和测试假值，例如 `token`、`secret-token`、`tg-token`。

### 2. 配置脱敏

`quantflow/common/config.py` 中定义了：

- `SENSITIVE_FIELDS = {"token", "secret", "api_key", "passphrase", "password"}`
- `save_config(..., sanitize=True)` 默认会对上述字段输出 `***REDACTED***`

结论：

- 配置持久化路径默认具备敏感字段脱敏能力。

### 3. 运行时凭证注入

`quantflow/cli/main.py` 中的 `_load_gateway_config_from_env()` 要求：

- `OKX_API_KEY`
- `OKX_SECRET`
- `OKX_PASSPHRASE`

缺失时直接抛出参数错误，不允许以空凭证进入 `live` 模式。

结论：

- 实盘敏感信息未被设计为源码内置常量。

### 4. 包内容风险

当前仓库已包含：

- `.dockerignore`
- `.gitignore`
- `.env.example`

当前发布产物形式为 wheel 与 sdist，不包含项目根目录下未追踪的本地凭证文件。

## 当前未覆盖的外部安全项

以下项目需要额外工具或外部平台，当前仓库中没有现成自动化结果：

- SCA / CVE 报告导出
- VirusTotal 扫描
- 镜像漏洞扫描
- 签名证书与时间戳验证

## 结论

在仓库内可验证的范围内，当前版本未见明显的敏感信息硬编码问题，且实盘凭证处理方式符合最小暴露原则。
