# v0.9.0 回滚计划

## 代码回滚
- `git revert` 至 `1f8803f`（v0.8.0）；或 `pip install quantflow==0.8.0`

## 数据回滚
- 新后缀分区（`*-OKX/-BINANCE/-BYBIT`）与旧分区物理隔离：删除对应目录即回退，旧 `BTC_USDT/` 全程未改动
- 归档操作可逆：按 `data/parquet_archive/manifest_*.json` 将目录移回原位
- meta relabel 可逆：`meta_funding_rate/BTC_USDT-OKX` rename 回 `BTC_USDT`

## 发布回滚
- `gh release delete v0.9.0 --yes && git push origin :refs/tags/v0.9.0`
