# QuantFlow v0.1.1 Rollback Plan

发布日期：2026-06-03

## 目标

如果 `v0.1.1` 的自动化发布链、CLI 运行链或 Docker 部署链出现异常，能够快速回退到上一稳定版本 `v0.1.0` 或稳定提交。

## 回滚触发条件

- `quantflow status` 无法执行。
- `python scripts/check_env.py` 无法返回 `READY`。
- `scripts/build_release.py` 无法按预期生成制品与校验文件。
- GitHub Release 工作流无法产出预期资产。
- Docker 服务无法达到 healthy 状态。

## 回滚目标

- 首选 Tag：`v0.1.0`
- 若需源码级回退：回退到 `38ef990` 之前的稳定点，并重新验证。

## Python package 回滚

```powershell
pip uninstall -y quantflow
pip install <previous-wheel>
quantflow status
python scripts\check_env.py
```

## 源码与 Tag 回滚

```powershell
git checkout v0.1.0
pip install -e ".[dev]"
python -m quantflow.cli.main status
```

## Docker Compose 回滚

```powershell
git checkout v0.1.0
docker compose -f docker\docker-compose.yaml down
docker compose -f docker\docker-compose.yaml build --no-cache
docker compose -f docker\docker-compose.yaml up -d
```

## 数据保护要求

- 不删除 `data/`
- 先备份 `.env` 与自定义 YAML
- 如需回退数据库，先复制 `data/quantflow.duckdb`
