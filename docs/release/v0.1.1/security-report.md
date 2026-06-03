# QuantFlow v0.1.1 Security Report

发布日期：2026-06-03

## 范围说明

`v0.1.1` 的安全结论与 `v0.1.0` 基本一致，本次重点增加的是发布自动化链的最小权限与资产完整性。

## 检查结果

### 1. 敏感信息策略

- 实盘密钥仍通过环境变量注入。
- 配置保存仍默认对敏感字段脱敏。

### 2. 资产完整性

- 每个发布资产生成独立 `.sha256`
- 汇总生成 `SHA256SUMS.txt`
- 生成 `release-manifest.json` 记录版本、Tag、资产路径和摘要

### 3. Release workflow 权限

- 仅申请 `contents: write`
- 用 `GH_TOKEN=${{ github.token }}` 驱动 `gh release create/upload`

## 未覆盖项

- 外部 SCA / CVE 平台正式报告
- VirusTotal
- 桌面安装器签名与公证
