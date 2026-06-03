# QuantFlow 发布完成标准

发布日期：2026-06-03

## 当前版本附加要求

除既有质量门禁外，`v0.1.2` 要求：

- GitHub Release 资产只包含当前版本文件
- 主包、单文件 checksum、汇总 checksum、manifest 四者一致
- 安装后 `quantflow status` 的版本号与发布版本一致

## 当前版本交付物清单

- `CHANGELOG.md`
- `requirements-lock.txt`
- `scripts/build_release.py`
- `.github/workflows/release.yml`
- `dist/quantflow-0.1.2.tar.gz`
- `dist/quantflow-0.1.2.tar.gz.sha256`
- `dist/quantflow-0.1.2-py3-none-any.whl`
- `dist/quantflow-0.1.2-py3-none-any.whl.sha256`
- `dist/SHA256SUMS.txt`
- `dist/release-manifest.json`
- `docs/release/v0.1.2/release-notes.md`
- `docs/release/v0.1.2/upgrade-guide.md`
- `docs/release/v0.1.2/rollback-plan.md`
- `docs/release/v0.1.2/known-issues.md`
- `docs/release/v0.1.2/test-report.md`
- `docs/release/v0.1.2/security-report.md`
