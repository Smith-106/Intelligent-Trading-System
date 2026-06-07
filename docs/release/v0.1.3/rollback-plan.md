# QuantFlow v0.1.3 Rollback Plan

发布日期：2026-06-07

## 目标

若 `v0.1.3` 的版本对齐、发布资产或安装链出现异常，快速回退到上一稳定发布基线。

## 回滚目标

- 首选：`v0.1.2`
- 若 `v0.1.2` 本身仍存在资产漂移，则暂停对外分发，重新整理发布候选

## 触发条件

- Git tag / Release 资产与当前源码版本不一致
- `quantflow status` 显示的版本号与安装版本不一致
- `SHA256SUMS.txt`、单文件 `.sha256` 与 `release-manifest.json` 不一致
- `sdist` 再次包含非发布内容

## 回滚动作

```powershell
git checkout v0.1.2
pip install -e ".[dev]"
python -m quantflow.cli.main status
```

如为包安装环境：

```powershell
pip uninstall -y quantflow
pip install <previous-wheel>
quantflow status
```
