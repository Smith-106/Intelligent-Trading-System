# v0.9.0 升级指南（0.8.0 → 0.9.0）

## 破坏性变更
无。全部新参数均有安全默认值；无后缀旧分区继续可读（resolver bare 兜底）。

## 新增能力
- 多交易所下载命令：`download-binance` / `download-bybit` / `download-bybit-funding` / `download-bybit-oi`
- OKX 批量：`download --symbols BTC/USDT,ETH/USDT,...`
- 交易所后缀分区：`BTC_USDT-OKX` / `-BINANCE` / `-BYBIT`（写入侧默认开启）
- 读侧解析层 `DataStore.resolve_symbol()`：优先级 `(-OKX, -BINANCE, bare)`

## 升级步骤
1. `pip install -e ".[dev]" && pip install quantflow-0.9.0-py3-none-any.whl`
2. （可选）Binance 存量重跑至 `-BINANCE` 分区：`quantflow download-binance --symbol BTC/USDT --timeframe 1d --start 2019-01 --end <最后完整月>`
3. （可选，网络恢复后）OKX 重跑至 `-OKX`：`quantflow download --symbols ... --timeframe 1h`
4. （可选）归档旧混合分区：`python scripts/archive_legacy_partitions.py`（dry-run 先行，确认后 `--apply`）

## 注意事项
- 后缀永不进入 ccxt/gateway 路径，交易符号语义不变
- Binance archive 近期月份 openTime 为微秒单位，本版已自适应（勿回移除 `_normalize_epoch_ms`）
