# QuantFlow v0.1.3 Security Report

发布日期：2026-06-07

## 范围

本轮候选的安全重点是四件事：

- 运行时依赖不落入已知高危版本
- 发布资产不混入凭证和工作流垃圾
- 安装后的 wheel 依赖可审计
- 回滚与升级路径仍保持可执行

## 检查结论

- 实盘凭证仍未内置在源码或发布资产中；仓库中保留的是 `.env.example` 占位，不包含真实值。
- `sdist` 通过显式文件选择排除 `.workflow`、`.codegraph`、`tests` 等非发布内容。
- `requirements-lock.txt` 已从干净 wheel 环境重建，移除了旧 editable Git 依赖和宿主机开发污染。
- `aiohttp` 最低版本已提升到 `3.14.0`，避免把本地曾发现的 `3.13.5` 漏洞版本保留为发布下限。
- `release-manifest.json` 与 `SHA256SUMS.txt` 作为 `v0.1.3` 的二次核验基线。

## 依赖扫描结论

### 本地旧环境发现

- 仓库旧 `.venv` 中曾解析到 `aiohttp==3.13.5`
- 该版本命中过 `CVE-2026-34993`、`CVE-2026-47265`

### 当前发布候选基线

- 干净 installed-wheel 环境解析到 `aiohttp==3.14.0`
- 运行时锁已同步到 `aiohttp==3.14.0`
- 已在干净 wheel 环境执行：

```powershell
pip-audit --ignore-vuln PYSEC-2026-196
```

实测结论：

- QuantFlow 运行时依赖无已知高危漏洞
- 输出为 `No known vulnerabilities found`
- `quantflow (0.1.3)` 因未发布到 PyPI 被标记为 `Dependency not found on PyPI and could not be audited`，这不构成运行时漏洞
