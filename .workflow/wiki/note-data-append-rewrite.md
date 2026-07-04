# DataStore/FeatureStore 追加写入重写整月 Parquet 分区

**Source**: ANL-001 性能分析 (C4)
**Tags**: performance, data, io

DataStore.save() 和 FeatureStore.save_features() 对小批量追加采用"读整月 Parquet → concat → 去重 → 排序 → 重写"模式。随着历史分区增大，追加 IO 成本随之增长。

优化方向：缓冲写入更大批次、使用日批次文件 + 定期压缩、保持时间点正确性和去重语义、添加分区增长下的追加 benchmark。
