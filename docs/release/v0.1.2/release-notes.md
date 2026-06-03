# QuantFlow v0.1.2 Release Notes

发布日期：2026-06-03

## 发布定位

`v0.1.2` 是对 `v0.1.1` 自动化发布链的洁净化修正版，目标是确保 GitHub Release 只发布当前版本资产，不混入历史版本校验文件。

## 本版本重点

### 1. 修正 Release 资产选择

- 将 `.github/workflows/release.yml` 从宽通配上传改为当前版本的显式文件列表。
- `upload-artifact` 与 `gh release create/upload` 现在只上传：
  - `quantflow-0.1.2.tar.gz`
  - `quantflow-0.1.2-py3-none-any.whl`
  - 对应两个 `.sha256`
  - `SHA256SUMS.txt`
  - `release-manifest.json`

### 2. 修正 manifest 细节

- `scripts/build_release.py` 现在显式记录当前版本每个资产对应的 checksum 文件路径。
- 便于后续发布核验和下载清单自动消费。

### 3. 版本与发布一致性保持

- `quantflow status` 在已安装 wheel 中正确显示 `Version 0.1.2`。
- `v0.1.2` Tag、源码提交、Release 资产按同一版本闭环验证。

## 版本制品

- `dist/quantflow-0.1.2.tar.gz`
- `dist/quantflow-0.1.2.tar.gz.sha256`
- `dist/quantflow-0.1.2-py3-none-any.whl`
- `dist/quantflow-0.1.2-py3-none-any.whl.sha256`
- `dist/SHA256SUMS.txt`
- `dist/release-manifest.json`

## 已验证事项

- `python scripts/build_release.py --tag v0.1.2`
- `python -m ruff check . --output-format concise`
- `python -m mypy quantflow tests`
- `python -m pytest tests --cov=quantflow --cov-report=term-missing --cov-report=term:skip-covered -q`
- `python scripts/check_env.py`
- 干净环境安装 `quantflow-0.1.2-py3-none-any.whl` 后，`quantflow status` 正确显示 `Version 0.1.2`
- GitHub Actions `CI`
- GitHub Actions `Release`

## 非本次交付范围

- 桌面安装器矩阵
- 数字签名 / 公证 / 应用商店提审
- 自动更新服务与灰度分发
