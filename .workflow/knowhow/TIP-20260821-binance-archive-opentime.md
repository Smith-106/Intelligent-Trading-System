---
title: Binance archive openTime 单位漂移：毫秒→微秒导致未来泄漏误报
type: tip
created: 2026-08-21T13:05:22.382Z
---

## 现象
Binance 公共归档（data.binance.vision）月度 K 线 CSV 的 openTime 列单位已变更：近期月份为 16 位微秒时间戳，2025 前文件仍为 13 位毫秒。若硬编码 unit='ms' 解析，新数据时间戳膨胀 1000 倍（显示为 5 万年后），触发"未来数据泄漏"校验误报（实测 92 行全中）。

## 修复
幅值判别自适应：< 1e14 视为毫秒，>= 1e14 整除 1000 转毫秒（合法毫秒时间戳不可能 >= 1e14，那约是公元 5138 年）。实现见 quantflow/data/binance_fetcher.py `_normalize_epoch_ms`。

## 启示
外部归档类数据源的列格式会随时间漂移，解析层必须有单位/格式防御；接入后立即用 max(timestamp) vs now() 冒烟。
