# QuantFlow v0.1.2 Upgrade Guide

发布日期：2026-06-03

## 适用对象

- 已在使用 `v0.1.1`，需要切换到干净 Release 资产版本的使用者。
- 依赖 GitHub Release 下载制品的维护者或部署方。

## 升级内容

`v0.1.2` 不引入业务功能变更，重点是发布资产清单清洁化：

- 当前版本 Release 不再混入历史版本 checksum 文件
- 发布 manifest 与 checksum 路径一致
- 已安装 wheel 的状态页版本显示正确

## Python 安装升级

```powershell
pip install --upgrade dist\quantflow-0.1.2-py3-none-any.whl
quantflow status
```

## Docker Compose 升级

```powershell
docker compose -f docker\docker-compose.yaml build --no-cache
docker compose -f docker\docker-compose.yaml up -d
```

## 维护者发布步骤

```powershell
python scripts\build_release.py --tag v0.1.2
git tag v0.1.2
git push origin main
git push origin v0.1.2
```
