# QuantFlow v0.1.0 Test Report

发布日期：2026-06-03

## 测试结论

`v0.1.0` 当前代码基线满足本仓库定义的测试门禁：

- 单元与集成测试通过。
- `mypy --strict` 通过。
- 构建成功。
- CLI 环境预检通过。
- 最近一次 GitHub Actions CI 为成功状态。

## 本地验证结果

### 1. 类型检查

命令：

```powershell
python -m mypy quantflow tests
```

结果：

- `Success: no issues found in 139 source files`

### 2. 测试与覆盖率

命令：

```powershell
python -m pytest tests --cov=quantflow --cov-report=term-missing --cov-report=term:skip-covered -q
```

结果：

- `587 passed, 2 skipped`
- 总覆盖率 `99.96%`
- 覆盖率门禁 `70%` 已满足

未完全覆盖文件：

- `quantflow/data/fetcher.py` 缺失 2 行覆盖

### 3. 构建验证

命令：

```powershell
python -m build
```

结果：

- 成功生成 `quantflow-0.1.0.tar.gz`
- 成功生成 `quantflow-0.1.0-py3-none-any.whl`

### 4. 环境预检

命令：

```powershell
python scripts/check_env.py
```

结果：

- 输出 `READY: All required checks passed.`

### 5. 远端 CI

最近一次成功运行：

- Workflow：`CI`
- Branch：`main`
- Commit：`2143bb4`
- Run ID：`26863732118`
- 状态：`success`

## 结论

对 Python CLI + Docker 交付范围内的核心质量门禁，当前证据充分。
