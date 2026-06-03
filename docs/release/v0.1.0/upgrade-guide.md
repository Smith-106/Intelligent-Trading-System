# QuantFlow v0.1.0 Upgrade Guide

发布日期：2026-06-03

## 适用对象

- 从源码运行切换到标准 Python package 安装的使用者。
- 已有旧工作目录，需要平滑升级到 `v0.1.0` 的单机部署环境。

## 升级前检查

1. 备份当前 `.env`、自定义 YAML 配置和 `data/` 目录。
2. 记录当前运行方式：源码直跑、虚拟环境安装，还是 Docker Compose。
3. 确认实盘环境已经保存以下变量，不要依赖历史 shell 会话：
   - `OKX_API_KEY`
   - `OKX_SECRET`
   - `OKX_PASSPHRASE`
   - 可选告警变量，如 `TELEGRAM_BOT_TOKEN`

## Python 安装升级

1. 进入目标虚拟环境。
2. 安装新版本：

```powershell
pip install --upgrade dist\quantflow-0.1.0-py3-none-any.whl
```

3. 执行预检：

```powershell
python scripts\check_env.py
quantflow status
```

## Docker Compose 升级

1. 拉取最新源码或切换到 `v0.1.0` 对应提交。
2. 在 `docker/` 目录重建并启动：

```powershell
docker compose build --no-cache
docker compose up -d
```

3. 验证健康状态和指标端点：

```powershell
docker compose ps
curl http://localhost:18000/metrics
```

## 配置兼容性

- 默认配置路径仍兼容 `quantflow/config/default.yaml`。
- 安装后运行时会自动解析包内默认配置，不要求从源码树启动。
- 自定义配置仍建议通过命令行 `--config` 或环境变量 `QUANTFLOW_*` 覆盖。

## 数据兼容性

- `v0.1.0` 不引入数据目录格式破坏性变更。
- 现有 Parquet / DuckDB 数据可继续复用。
- 如需谨慎升级，建议先备份 `data/quantflow.duckdb` 与 `data/parquet/`。

## 升级后回归检查

1. `quantflow status`
2. `quantflow research --strategy trend_following --symbol BTC/USDT`
3. 如使用 Docker，检查 `/metrics` 返回 `200`
4. 如使用实盘或模拟盘，确认环境变量注入正确
