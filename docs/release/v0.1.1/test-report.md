# QuantFlow v0.1.1 Test Report

发布日期：2026-06-03

## 测试结论

`v0.1.1` 在 `v0.1.0` 的质量门禁基础上，新增验证了自动化发布链本身。

## 本地验证结果

### 1. 发布脚本

命令：

```powershell
python scripts/build_release.py --tag v0.1.1
```

结果：

- 成功生成 `quantflow-0.1.1.tar.gz`
- 成功生成 `quantflow-0.1.1-py3-none-any.whl`
- 成功生成 `.sha256`、`SHA256SUMS.txt`、`release-manifest.json`

### 2. Ruff

命令：

```powershell
python -m ruff check . --output-format concise
```

结果：

- 全量通过

### 3. Mypy

命令：

```powershell
python -m mypy quantflow tests
```

结果：

- `Success: no issues found in 139 source files`

### 4. Pytest 与覆盖率

命令：

```powershell
python -m pytest tests --cov=quantflow --cov-report=term-missing --cov-report=term:skip-covered -q
```

结果：

- `587 passed, 2 skipped`
- 总覆盖率 `99.96%`

### 5. 环境预检

命令：

```powershell
python scripts/check_env.py
```

结果：

- 返回 `READY`

### 6. Release workflow

远端验证项：

- 推送 `v0.1.1` Tag 后自动运行
- 生成 GitHub Release 资产与 workflow artifact
