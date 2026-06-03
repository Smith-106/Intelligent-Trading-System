# QuantFlow 发布完成标准

发布日期：2026-06-03

## 目的

将你提供的“桌面安装器发布清单”改写为适用于 QuantFlow 当前产品形态的标准。当前项目的正式交付形态是：

- Python package：`sdist + wheel`
- Docker Compose：单机部署
- CLI：`quantflow`

因此，以下项目视为“当前版本必须完成”，而不是 `.exe/.msi/.dmg/.pkg`、代码签名或应用商店提审。

## 一票否决项

满足任一项即禁止发布：

- 存在 P0 缺陷，导致 `quantflow status`、核心研究/运行链路不可用。
- `python -m build` 失败。
- `python -m mypy quantflow tests` 失败。
- `python -m pytest tests --cov=quantflow ...` 失败。
- 核心冒烟失败：CLI 无法启动，或 Docker 服务无法健康运行。
- 存在真实硬编码敏感信息。
- 无回滚方案。
- 升级导致 `data/` 或自定义配置不可恢复。

## 阶段一：代码准入

必须满足：

- 计划内功能完成，或已明确排除。
- 关键代码路径通过 review 并合入 `main`。
- `ruff`、`mypy`、`pytest` 全绿。
- 无调试残留和真实敏感信息。
- 版本号、`CHANGELOG.md`、升级说明已更新。
- 依赖清单已锁定或至少完成环境快照归档。

## 阶段二：构建打包

必须满足：

- CI 自动构建成功，不依赖本地手工改包。
- 产物包含：
  - `dist/quantflow-<version>.tar.gz`
  - `dist/quantflow-<version>-py3-none-any.whl`
  - 对应 `.sha256`
- 干净环境安装可运行 CLI。
- Docker Compose 构建和健康检查通过。

不适用项：

- 桌面安装器签名、公证、商店审核。

## 阶段三：验收测试

必须满足：

- 干净虚拟环境安装 wheel 后，`quantflow status` 正常。
- `python scripts/check_env.py` 返回 `READY`。
- Docker Compose 启动后 `/metrics` 返回 `200`。
- 关键数据路径和默认配置可加载。
- 已知问题清单已文档化。
- 回滚方案已写明并可操作。

## 阶段四：发布上线

必须满足：

- 发布说明已归档。
- 制品与 Hash 已归档。
- GitHub Actions 最近一次 `main` 构建成功。
- 若对外分发，则下载入口应指向正确版本产物。

## 阶段五：运行确认

必须满足：

- 发布后至少完成一次真实环境冒烟。
- 若使用 Docker，服务保持 healthy。
- 若使用 CLI 安装，关键命令可运行。
- Git Tag、Release Notes、测试报告、安全报告、回滚方案、Known Issues 已归档。

## 当前版本交付物清单

- `CHANGELOG.md`
- `requirements-lock.txt`
- `dist/quantflow-0.1.0.tar.gz`
- `dist/quantflow-0.1.0.tar.gz.sha256`
- `dist/quantflow-0.1.0-py3-none-any.whl`
- `dist/quantflow-0.1.0-py3-none-any.whl.sha256`
- `docs/release/v0.1.0/release-notes.md`
- `docs/release/v0.1.0/upgrade-guide.md`
- `docs/release/v0.1.0/rollback-plan.md`
- `docs/release/v0.1.0/known-issues.md`
- `docs/release/v0.1.0/test-report.md`
- `docs/release/v0.1.0/security-report.md`

## 明确不在当前版本闭环内的事项

以下事项只有在 QuantFlow 未来转向桌面终端产品时才需要纳入“发布完成”定义：

- Windows / macOS / Linux 桌面安装器矩阵
- 数字签名与 Apple notarization
- 应用商店审核
- 自动更新服务与增量更新包
- SmartScreen / Gatekeeper / VirusTotal 分发侧验证
