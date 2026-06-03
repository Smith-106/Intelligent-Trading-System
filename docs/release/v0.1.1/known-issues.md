# QuantFlow v0.1.1 Known Issues

发布日期：2026-06-03

## 已知限制

### 1. 实盘凭证仍需外部注入

- `OKX_API_KEY`、`OKX_SECRET`、`OKX_PASSPHRASE` 不会随发布资产分发。

### 2. 可选 ML 依赖默认不安装

- `torch`、`transformers`、`qlib` 仍为可选依赖。

### 3. 当前交付仍非桌面安装器产品

- 发布资产为 Python package 和 GitHub Release 附件，不是桌面安装包。

### 4. Release workflow 依赖 GitHub 平台权限

- 自动化发布要求仓库 `GITHUB_TOKEN` 具备 `contents: write` 权限。
- 若仓库策略收紧，该工作流会失败，但不影响本地构建和安装使用。
