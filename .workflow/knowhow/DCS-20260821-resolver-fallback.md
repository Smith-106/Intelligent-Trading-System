---
title: 交易所后缀分区隔离 + 显式读侧 resolver（否决透明 fallback）
type: decision
created: 2026-08-21T13:05:57.010Z
---

## 决策
多交易所数据物理分区按交易所后缀隔离：BTC_USDT-OKX / -BINANCE / -BYBIT（SYMBOL_PATTERN 拒绝 '.' 允许 '-'，后缀零 validator 改动）。交割合约确定性映射到原生 V5 id：BTC/USDT:USDT-260904 → BTCUSDT-04SEP26（Bybit 交割命名为 DDMMMYY，实测发现；19 字符合法）。

## 读侧解析
DataStore.resolve_symbol() 显式优先级链 (-OKX, -BINANCE, bare)：web 读路径优先干净源，无后缀分区时 bare 兜底零行为变化。调用点显式 opt-in + provenance 日志。

## 否决项（三模型一致）
- 直接切换默认 symbol：-OKX 缺失时 store.query 静默空帧 → web 静默降级 demo 伪数据污染研究。
- query 内透明 fallback：掩盖混源、回测输入无声漂移、违背仓库 fail-loud 纪律（ISS-20260723 系列）。

## 不变量
后缀永不进入 ccxt/gateway 路径（交易符号语义不变）。
