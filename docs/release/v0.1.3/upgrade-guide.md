# QuantFlow v0.1.3 Upgrade Guide

发布日期：2026-06-07

## 适用对象

- 当前使用 `v0.1.2`，但需要切换到与最新源码一致的发布候选的维护者。
- 依赖本地构建或 GitHub Release 制品的验证者。

## 升级内容

`v0.1.3` 不引入新的交易品类，但包含已经进入候选制品边界的运行时与发布治理变更：

- 版本重新对齐到当前 `HEAD`
- 三个核心模板策略的事件驱动热路径改为增量计算
- benchmark 新增 `runtime.three_strategy_bars_per_sec`
- `sdist` 收紧为发布安全内容
- `requirements-lock.txt` 基于干净 wheel 环境重建
- `SHA256SUMS.txt` 与 `release-manifest.json` 将针对 `0.1.3` 重建

## 升级前注意

- 若旧环境中存在 `aiohttp<3.14.0`，应重建虚拟环境后再安装 `v0.1.3`。
- 若你需要复现实测运行时依赖，请先安装 `requirements-lock.txt`，再安装 wheel。

## Python 安装升级

```powershell
python -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv-release\Scripts\python.exe -m pip install --upgrade dist\quantflow-0.1.3-py3-none-any.whl
quantflow status
```

## Docker Compose 升级

```powershell
docker compose -f docker\docker-compose.yaml build --no-cache
docker compose -f docker\docker-compose.yaml up -d
```

## 维护者发布步骤

```powershell
python scripts\build_release.py --tag v0.1.3
git tag v0.1.3
git push origin main
git push origin v0.1.3
```
