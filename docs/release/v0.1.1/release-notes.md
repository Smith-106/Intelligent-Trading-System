# QuantFlow v0.1.1 Release Notes

发布日期：2026-06-03

## 发布定位

`v0.1.1` 是在 `v0.1.0` 基础上的发布一致性修正版，目标不是扩展业务功能，而是把以下事项统一到同一源码与 Tag：

- 版本号
- Git Tag
- GitHub Release 工作流
- 发布资产与校验文件
- 发布文档证据

## 本版本重点

### 1. 自动化发布闭环

- 新增 `scripts/build_release.py`，统一生成：
  - `sdist`
  - `wheel`
  - 每个资产对应的 `.sha256`
  - `dist/SHA256SUMS.txt`
  - `dist/release-manifest.json`
- 新增 `.github/workflows/release.yml`，支持：
  - `push tags: v*`
  - `workflow_dispatch`
  - GitHub Release 资产上传

### 2. 版本与 Tag 一致性修正

- 保留 `v0.1.0` 作为历史版本。
- 将当前自动化发布链对应的正式源码版本提升为 `v0.1.1`。
- 避免“旧 Tag 指向旧源码，但 Release 资产来自新源码”的不一致问题。

### 3. 发布标准补强

- 发布标准中新增“Tag 驱动的自动化发布资产生成”要求。
- 发布报告中新增自动化发布链的验证项。

## 版本制品

- `dist/quantflow-0.1.1.tar.gz`
- `dist/quantflow-0.1.1.tar.gz.sha256`
- `dist/quantflow-0.1.1-py3-none-any.whl`
- `dist/quantflow-0.1.1-py3-none-any.whl.sha256`
- `dist/SHA256SUMS.txt`
- `dist/release-manifest.json`

## 已验证事项

- `python scripts/build_release.py --tag v0.1.1`
- `python -m ruff check . --output-format concise`
- `python -m mypy quantflow tests`
- `python -m pytest tests --cov=quantflow --cov-report=term-missing --cov-report=term:skip-covered -q`
- `python scripts/check_env.py`
- GitHub Actions `CI`
- GitHub Actions `Release` workflow 已配置，用于 `v0.1.1` Tag 推送后的远端发布验证

## 适用场景

- 本地研究 / 回测。
- 单机 Docker Compose 部署。
- Python CLI 的源码、制品、Release 资产一致性交付。

## 非本次交付范围

- Windows `.exe/.msi`、macOS `.dmg/.pkg`、Linux `.deb/.rpm` 桌面安装器。
- 数字签名、公证、应用商店提审。
- 自动更新服务、增量更新包和桌面端灰度分发。
