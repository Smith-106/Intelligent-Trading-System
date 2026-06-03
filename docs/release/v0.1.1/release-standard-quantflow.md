# QuantFlow 发布完成标准

发布日期：2026-06-03

## 目的

本标准适用于 QuantFlow 当前产品形态：

- Python package：`sdist + wheel`
- Docker Compose：单机部署
- CLI：`quantflow`

`v0.1.1` 起，正式发布除质量门禁外，还要求：

- 版本号与源码一致
- Git Tag 与源码提交一致
- Release workflow 与发布资产一致

## 一票否决项

- 核心 CLI 不可用
- `python -m build` 失败
- `python scripts/build_release.py --tag vX.Y.Z` 失败
- `mypy` / `pytest` 失败
- 存在真实敏感信息硬编码
- 无回滚方案

## 阶段一：代码准入

- 计划内功能完成或排除
- 质量门禁全绿
- 版本号、`CHANGELOG`、发布文档同步更新

## 阶段二：构建打包

- CI 自动构建成功
- Release workflow 可由 `vX.Y.Z` Tag 触发
- 产物包含：
  - `dist/quantflow-<version>.tar.gz`
  - `dist/quantflow-<version>-py3-none-any.whl`
  - 对应 `.sha256`
  - `dist/SHA256SUMS.txt`
  - `dist/release-manifest.json`

## 阶段三：验收测试

- 干净环境可安装 wheel 并运行 `quantflow status`
- `python scripts/check_env.py` 返回 `READY`
- Docker Compose 健康检查通过
- 已知问题、测试报告、安全报告、回滚方案齐全

## 阶段四：发布上线

- 推送 `vX.Y.Z` Tag
- GitHub Release 自动生成
- Release 资产与源码版本一致

## 阶段五：运行确认

- Release workflow 成功
- GitHub Release 资产可下载
- 本地校验值与发布校验值一致

## 当前版本交付物清单

- `CHANGELOG.md`
- `requirements-lock.txt`
- `scripts/build_release.py`
- `.github/workflows/release.yml`
- `dist/quantflow-0.1.1.tar.gz`
- `dist/quantflow-0.1.1.tar.gz.sha256`
- `dist/quantflow-0.1.1-py3-none-any.whl`
- `dist/quantflow-0.1.1-py3-none-any.whl.sha256`
- `dist/SHA256SUMS.txt`
- `dist/release-manifest.json`
- `docs/release/v0.1.1/release-notes.md`
- `docs/release/v0.1.1/upgrade-guide.md`
- `docs/release/v0.1.1/rollback-plan.md`
- `docs/release/v0.1.1/known-issues.md`
- `docs/release/v0.1.1/test-report.md`
- `docs/release/v0.1.1/security-report.md`

## 非当前范围

- 桌面安装器矩阵
- 数字签名、公证、应用商店审核
- 自动更新服务与灰度分发
