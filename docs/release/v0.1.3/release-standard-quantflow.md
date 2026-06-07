# QuantFlow v0.1.3 Release Candidate Standard

发布日期：2026-06-07

## 审计标准映射

本仓库交付物是 Python `sdist/wheel` + GitHub Release 资产，不适用桌面安装器签名、SmartScreen 和 VirusTotal 误报率指标。对应发布标准映射如下：

- 代码准入：版本、测试、静态检查、依赖锁、敏感信息扫描
- 构建打包：干净环境构建、可复现 artifact、SHA256、内容治理
- 验收测试：installed-wheel 冒烟、CLI 核心命令、基准命令
- 发布上线：commit / tag / GitHub Release / 远端资产对齐
- 运行确认：远端 Release 页面和下载资产二次核验

## 当前版本附加要求

除既有质量门禁外，`v0.1.3` 要求：

- 源码版本、包版本、后续 tag / release 目标版本一致
- `sdist` 不包含 `.workflow`、`.codegraph`、`tests`、缓存与运行态内容
- 主包、单文件 checksum、汇总 checksum、manifest 四者一致
- `requirements-lock.txt` 必须是干净 wheel 运行时锁，不能混入 editable Git 行或宿主机开发依赖
- 性能热路径优化必须在 changelog / release notes / tests 中同时有对应证据

## 当前本地门禁

- `scripts/check_env.py` 返回 `READY`
- `ruff check .` 通过
- `mypy quantflow` 通过
- `pytest tests -q` 通过
- benchmark JSON 无失败项
- 干净 wheel 环境 `quantflow --help` / `quantflow status` 通过
- 干净 wheel 环境 `pip-audit` 不得出现 QuantFlow 运行时高危漏洞

## 当前版本交付物清单

- `CHANGELOG.md`
- `LICENSE`
- `requirements-lock.txt`
- `scripts/build_release.py`
- `dist/quantflow-0.1.3.tar.gz`
- `dist/quantflow-0.1.3.tar.gz.sha256`
- `dist/quantflow-0.1.3-py3-none-any.whl`
- `dist/quantflow-0.1.3-py3-none-any.whl.sha256`
- `dist/SHA256SUMS.txt`
- `dist/release-manifest.json`
- `docs/release/v0.1.3/release-notes.md`
- `docs/release/v0.1.3/upgrade-guide.md`
- `docs/release/v0.1.3/rollback-plan.md`
- `docs/release/v0.1.3/known-issues.md`
- `docs/release/v0.1.3/test-report.md`
- `docs/release/v0.1.3/security-report.md`
