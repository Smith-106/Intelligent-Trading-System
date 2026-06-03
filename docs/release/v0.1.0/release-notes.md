# QuantFlow v0.1.0 Release Notes

发布日期：2026-06-03

## 发布定位

`v0.1.0` 是 QuantFlow 的首个可打包、可部署、可验证交付版本，覆盖以下链路：

- Python package 构建与安装。
- Docker Compose 本地部署与健康检查。
- CLI 状态自检与环境预检。
- 策略研究、回测验证、模拟盘/实盘统一运行骨架。

## 本版本重点

### 1. 发布链打通

- 修复打包后 CLI 运行时配置路径解析问题。
- 修复 Docker 构建上下文与运行健康检查链路。
- 在 GitHub Actions 中加入 `build`、`ruff format --check`、`ruff check`、`mypy`、CLI smoke test、`pytest`。

### 2. 运行稳定性增强

- 数据抓取连接失败后关闭异常连接状态，避免脏状态泄漏。
- 策略引擎在数据连接/抓取异常时执行重试，而不是直接退出进程。
- `scripts/check_env.py` 可直接给出“可运行 / 不可运行”结论。

### 3. 回测一致性修正

- 修正回测初始权益、权益连续性和交易 PnL 处理细节。
- 补齐相关回归测试，保证研究链路行为可重复验证。

### 4. 策略模板链扩展

- 新增 `volatility_breakout`、`funding_rate`、`momentum_rotation`、`ml_ensemble` 四条策略模板链。
- 保持 YAML 驱动扩展方式，不引入策略注册层破坏性重构。

## 版本制品

- `dist/quantflow-0.1.0.tar.gz`
- `dist/quantflow-0.1.0.tar.gz.sha256`
- `dist/quantflow-0.1.0-py3-none-any.whl`
- `dist/quantflow-0.1.0-py3-none-any.whl.sha256`

## 已验证事项

- `python -m build`
- `python -m mypy quantflow tests`
- `python -m pytest tests --cov=quantflow --cov-report=term-missing --cov-report=term:skip-covered -q`
- `python scripts/check_env.py`
- GitHub Actions `CI` on `main` for commit `2143bb4`

## 适用场景

- 本地研究 / 回测。
- 使用 Docker Compose 的单机部署。
- 个人或小团队的 Python CLI 交付。

## 非本次交付范围

- Windows `.exe/.msi`、macOS `.dmg/.pkg`、Linux `.deb/.rpm` 桌面安装器。
- 代码签名、公证、应用商店提审。
- 自动更新服务、增量更新包和桌面端灰度分发。
