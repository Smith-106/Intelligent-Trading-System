# QuantFlow v0.1.0 Rollback Plan

发布日期：2026-06-03

## 目标

在 `v0.1.0` 发布后，如果出现核心 CLI 不可用、Docker 服务无法启动、核心回测/运行链路异常，能够快速回退到上一已知稳定版本或稳定提交。

## 回滚触发条件

满足任一条件即触发回滚：

- `quantflow status` 无法执行。
- `python scripts/check_env.py` 在目标环境返回 `NOT READY`，且不是因为故意缺省的 live 凭证。
- Docker Compose 服务无法达到 healthy 状态。
- `/metrics` 端点不可用。
- 发现 P0 缺陷，例如核心命令不可运行、安装后无法加载默认配置、升级造成现有数据不可读。

## Python package 回滚

1. 保留现有 `.env` 与 `data/` 目录备份。
2. 卸载当前包：

```powershell
pip uninstall -y quantflow
```

3. 安装上一稳定 wheel 或直接从稳定提交重新安装：

```powershell
pip install <previous-wheel>
```

4. 执行回滚验证：

```powershell
quantflow status
python scripts\check_env.py
```

## 源码部署回滚

1. 记录当前异常提交。
2. 切换回上一稳定提交或发布 Tag：

```powershell
git checkout <stable-commit-or-tag>
pip install -e ".[dev]"
```

3. 验证：

```powershell
python -m quantflow.cli.main status
python scripts\check_env.py
```

## Docker Compose 回滚

1. 切换仓库到上一稳定提交或 Tag。
2. 在 `docker/` 目录重新构建并启动：

```powershell
docker compose down
docker compose build --no-cache
docker compose up -d
```

3. 验证：

```powershell
docker compose ps
curl http://localhost:18000/metrics
```

## 数据保护要求

- 回滚前不得删除 `data/`。
- 如涉及数据库文件替换，必须先复制 `data/quantflow.duckdb`。
- 不允许通过“清空数据目录”作为默认回滚动作。

## 演练记录

当前仓库已有以下可证明恢复能力的证据：

- Python package 构建成功，可在干净环境执行 CLI。
- Docker Compose 可健康启动，并通过 `/metrics` 进行检查。

说明：本次为单机 Python CLI / Docker 交付，没有桌面安装器，因此回滚演练以包安装和容器部署为主。
