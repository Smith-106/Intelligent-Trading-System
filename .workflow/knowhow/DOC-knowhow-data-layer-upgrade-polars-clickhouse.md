---
title: "数据层升级候选:Polars+ClickHouse/QuestDB;DuckDB QUALIFY ROW_NUMBER 实现 PIT 特征存储"
category: data,infra,upgrade-path
status: not-implemented,upgrade-candidate-only
createdBy: manage-harvest
sourceRef: deep-research-20260718 F14
note: "升级候选参考,非当前实现现状 — quantflow/data/ 仍为 DuckDB+Parquet+pandas。drift-realign DFT-3d9e5a2f 加 status 防误读为现状 (2026-07-26)。"
type: knowhow
---
数据层改进方向(来自 deep-research fetch 阶段):(1) Machine Learning for Trading 第3版数据层已迁移到 Polars(replacing pandas)做快速 expression-based 操作,并 benchmark 多种存储引擎(Parquet/DuckDB/kdb+/TimescaleDB/ClickHouse/QuestDB/InfluxDB)——QuantFlow 当前 Parquet+DuckDB 是子集,Polars 与列式时序库 ClickHouse/QuestDB 是具体升级候选;(2) DuckDB point-in-time 特征存储可用 QUALIFY ROW_NUMBER() OVER (PARTITION BY entity,label_ts ORDER BY as_of_date DESC) rank=1 窗口模式替代原生 ASOF JOIN 关键字,生成无泄漏可复现训练集。来源: stefan-jansen/machine-learning-for-trading + Medium DuckDB feature stores 文章。fetch 阶段提取,未单独对抗验证但方向明确。