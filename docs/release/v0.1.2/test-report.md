# QuantFlow v0.1.2 Test Report

发布日期：2026-06-03
复验日期：2026-06-06

## 本地验证

### 1. 发布脚本

```powershell
python scripts/build_release.py --tag v0.1.2
```

结果：

- 生成 `quantflow-0.1.2.tar.gz`
- 生成 `quantflow-0.1.2-py3-none-any.whl`
- 生成当前版本对应 `.sha256`
- 生成 `SHA256SUMS.txt`
- 生成 `release-manifest.json`

### 2. Ruff / Mypy / Pytest

```powershell
python -m ruff format --check quantflow tests scripts
python -m ruff check . --output-format concise
python -m mypy quantflow tests
python -m pytest tests --cov=quantflow --cov-report=term-missing --cov-report=term:skip-covered -q
```

结果：

- `ruff` 通过
- `mypy` 通过
- `601 passed, 2 skipped`
- 覆盖率 `98.17%`

### 3. Wheel 安装冒烟

在干净虚拟环境中安装 `quantflow-0.1.2-py3-none-any.whl` 后：

- `python -m quantflow.cli.main status` 通过
- `quantflow status` 通过
- `quantflow benchmark --bars 120 --trials 1 --wfo-windows 1 --skip-subprocess --json` 通过，`failures: []`
- 状态页版本号为 `0.1.2`

### 4. 环境 / Docker

- `python scripts/check_env.py` 返回 `READY`
- `docker compose -f docker/docker-compose.yaml config` 通过

### 5. 远端验证目标

- `CI` 成功
- `Release` 成功
- `v0.1.2` GitHub Release 资产只包含当前版本文件
