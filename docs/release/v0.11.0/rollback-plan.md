# v0.11.0 回滚计划

## 代码回滚
- `git revert` 至 v0.11.0 发布点的前一个 commit；或 `pip install quantflow==0.10.0`
- 前端独立版本：回滚后端不影响 Station 已构建产物（`quantflow/web/static/dist/`）

## 数据回滚
- 本版无 schema 迁移、无分区格式变更——无需数据回滚
- `.env.example` 重写不影响既有 `.env`（新增变量缺省安全）

## 配置回滚要点
- 同源策略收紧若误伤合法客户端：临时设置 `QUANTFLOW_STATION_TOKEN` 并让
  客户端携带 Bearer（token 模式下 Origin 缺失放行），而非关闭防护
- 限频代理白名单：仅添加确实受信的反代 peer IP

## 发布回滚
- `gh release delete v0.11.0 --yes && git push origin :refs/tags/v0.11.0`
