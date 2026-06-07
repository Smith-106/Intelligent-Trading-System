# QuantFlow v0.1.3 Release Notes

发布日期：2026-06-07

## 发布定位

`v0.1.3` 是围绕当前 `HEAD` 重新整理的发布候选，目标是把已经进入当前候选制品的运行时优化和发布治理改动，整理成一个可解释、可验证、可对齐远端 tag / release 的正式版本。

## 本版本重点

### 1. 性能热路径进入正式发布边界

- `trend_following`、`mean_reversion` 和 `volatility_breakout` 的事件驱动 `on_bar()` 路径改为增量计算，不再每根 bar 都重建完整 DataFrame。
- 新增 `quantflow/strategy/templates/_runtime.py`，集中提供 rolling mean、rolling std、RSI、ATR 和相关辅助计算。
- `quantflow benchmark` 新增 `runtime.three_strategy_bars_per_sec`，用于直接观察三策略组合下的事件热路径吞吐。
- 单元测试已补齐，确保增量路径与既有向量化信号路径保持一致。

### 2. 发布依赖与打包治理

- 项目版本从 `0.1.2` 提升到 `0.1.3`，避免继续复用已经与当前 `HEAD` 不一致的旧发布基线。
- `requirements-lock.txt` 已基于干净的 installed-wheel 环境重建，移除了旧 editable Git 依赖和宿主机开发依赖污染。
- `aiohttp` 最低版本抬升到 `3.14.0`，避免漏洞版本继续作为发布下限。
- `sdist` 只保留发布安全所需文件，排除 `.workflow`、`.codegraph`、`tests`、缓存目录与运行态工件。
- `wheel` 继续只分发 `quantflow` 运行时包。

### 3. 本地发布证据

- 质量门禁基线：
  - `python scripts/check_env.py`
  - `python -m ruff check .`
  - `python -m mypy quantflow`
  - `pytest tests -q`
  - `python -m quantflow.cli.main benchmark --bars 500 --trials 2 --wfo-windows 2 --skip-subprocess --json`
- 安装验证基线：
  - 干净虚拟环境安装 `quantflow-0.1.3-py3-none-any.whl`
  - `quantflow --help`
  - `quantflow status`
- 安全基线：
  - 干净 wheel 环境 `pip-audit` 无 QuantFlow 运行时高危漏洞
  - 凭证仍通过环境变量注入，不随源码或制品分发

### 4. 制品内容边界

- `sdist` 当前包含：
  - `requirements-lock.txt`
  - `quantflow/strategy/templates/_runtime.py`
- `sdist` 当前不包含：
  - `docs/release/`
  - `tests/`
  - `.workflow/`
- `wheel` 当前仅包含 `quantflow` 运行时包内容，不混入测试与工作流文件。

## 当前交付范围

- 性能热路径优化纳入正式 release 边界
- 版本元数据、运行时锁与发布文档对齐
- `sdist/wheel` 内容治理
- 本地 checksum / manifest / 安装烟测 / 安全扫描证据

## 远端发布前最后动作

- 提交本次候选修复并创建 `v0.1.3` tag
- 推送当前提交与 tag
- 创建或刷新 GitHub Release 资产
- 用远端发布页再次核验资产文件名、checksum 和 tag 指向
