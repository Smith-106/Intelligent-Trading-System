# QuantFlow v0.1.2 Rollback Plan

发布日期：2026-06-03

## 目标

若 `v0.1.2` 的 Release 资产、安装链或运行状态出现异常，快速回退到上一稳定版本。

## 回滚目标

- 首选：`v0.1.1`
- 若只接受完全干净资产清单：回退后暂停对外分发，待重新发布

## 触发条件

- GitHub Release 资产缺失当前版本主包或 checksum
- `quantflow status` 显示的版本号与安装版本不一致
- `SHA256SUMS.txt` 与单文件 `.sha256` 不一致

## 回滚动作

```powershell
git checkout v0.1.1
pip install -e ".[dev]"
python -m quantflow.cli.main status
```

如为包安装环境：

```powershell
pip uninstall -y quantflow
pip install <previous-wheel>
quantflow status
```
