# QuantFlow v0.1.1 Upgrade Guide

发布日期：2026-06-03

## 适用对象

- 已安装 `v0.1.0`，需要升级到自动化发布一致性版本的使用者。
- 准备基于 Git Tag 和 GitHub Release 分发资产的维护者。

## 升级内容

`v0.1.1` 不引入数据格式破坏性变更，升级重点是发布流程与版本一致性：

- 版本号从 `0.1.0` 提升到 `0.1.1`
- 新增自动化发布脚本与 Release workflow
- 统一源码、Tag、制品和发布文档

## Python 安装升级

```powershell
pip install --upgrade dist\quantflow-0.1.1-py3-none-any.whl
```

升级后验证：

```powershell
quantflow status
python scripts\check_env.py
```

## Docker Compose 升级

```powershell
docker compose -f docker\docker-compose.yaml build --no-cache
docker compose -f docker\docker-compose.yaml up -d
```

升级后验证：

```powershell
docker compose -f docker\docker-compose.yaml ps
curl http://localhost:18000/metrics
```

## 维护者发布步骤

```powershell
python scripts\build_release.py --tag v0.1.1
git tag v0.1.1
git push origin main
git push origin v0.1.1
```

推送 Tag 后，`Release` workflow 会基于该 Tag 生成并上传发布资产。
