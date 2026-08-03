---
title: 数据单源是 QuantFlow 最大结构性短板（阻塞两条演进线）
category: finding
createdBy: harvest
sourceRef: 20260803-001-analyze
---
# 数据单源是 QuantFlow 最大结构性短板（阻塞两条演进线）

**Source**: 20260803-001-analyze（finding F4，置信度 0.95；risk R3 概率5×影响5）
**Tags**: benchmark, data, strategy

DataFetcher 仅 CCXT/OKX 单一交易所 OHLCV（quantflow/data/fetcher.py:1-24），全库无 fetchFundingRate/持仓量/订单簿/链上采集（rg 验证）。调研材料判定"多源、高质量、point-in-time 数据比模型更难复制、是 Alpha 根本"。

该短板同时阻塞两条演进线：① 加密特色策略族（资金费率套利/订单簿微观结构因子以费率/OI 数据为前提）；② AI 多源特征工程（RD-Agent/qlib 管道需要多源输入）。因此演进路线图将"数据多源化先行"列为 P1 阶段任务（s2-multisource-data session，与 s1 并行启动）。

缓解路径：ccxt OKX fetchFundingRate/OI 采集（成本低、先行）→ 订单簿/链上（Tardis.dev/Glassnode 类数据商，选型与成本未定，列 P3 后候选）。
