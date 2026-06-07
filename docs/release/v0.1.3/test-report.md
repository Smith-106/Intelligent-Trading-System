# QuantFlow v0.1.3 Test Report

发布日期：2026-06-07

## 当前验证基线

以下结果来自当前 `v0.1.3` 发布候选的本地验证基线，覆盖代码质量、性能基准、打包内容和 installed-wheel 冒烟。

### 1. 代码与环境门禁

```powershell
python scripts/check_env.py
python -m ruff check .
python -m mypy quantflow
python -m pytest tests -q
python -m quantflow.cli.main benchmark --bars 500 --trials 2 --wfo-windows 2 --skip-subprocess --json
```

当前结果：

- `scripts/check_env.py`：`READY`
- `ruff check .`：通过
- `mypy quantflow`：通过
- `pytest tests -q`：`607 passed, 2 skipped`
- benchmark JSON：通过，`failures: []`

### 1.1 与 GitHub Release workflow 同构的门禁

```powershell
python -m ruff format --check quantflow tests scripts
python -m ruff check quantflow tests scripts
python -m mypy quantflow tests
python -m pytest tests --cov=quantflow --cov-report=term-missing -q
```

当前结果：

- `ruff format --check`：通过
- `ruff check quantflow tests scripts`：通过
- `mypy quantflow tests`：通过
- `pytest --cov`：`607 passed, 2 skipped`
- 总覆盖率：`97.90%`

### 2. 发布脚本与制品

```powershell
python scripts/build_release.py --tag v0.1.3
```

通过标准：

- 生成 `quantflow-0.1.3.tar.gz`
- 生成 `quantflow-0.1.3-py3-none-any.whl`
- 生成两个单文件 `.sha256`
- 生成 `dist/SHA256SUMS.txt`
- 生成 `dist/release-manifest.json`

### 3. 打包内容治理

本地检查结果：

- `sdist` 包含 `requirements-lock.txt`
- `sdist` 包含 `quantflow/strategy/templates/_runtime.py`
- `sdist` 不包含 `docs/release/`
- `sdist` 不包含 `tests/`
- `sdist` 不包含 `.workflow/`
- `wheel` 包含 `quantflow/strategy/templates/_runtime.py`
- `wheel` 不包含 `tests/`、`docs/release/`、`.workflow/`

### 4. 版本一致性

- `pyproject.toml` 版本号：`0.1.3`
- `quantflow.__version__`：`0.1.3`
- `release-manifest.json` 资产名与 `v0.1.3` 一致

### 5. Installed-wheel 冒烟

在干净虚拟环境中安装 `quantflow-0.1.3-py3-none-any.whl` 后：

- `quantflow --help`：通过
- `quantflow status`：通过
- 安装版本：`quantflow==0.1.3`

### 6. 远端发布前最后复验

- 推送后的 tag 指向
- GitHub Release 资产上传结果
- 远端 checksum 与本地 `SHA256SUMS.txt` 一致性
