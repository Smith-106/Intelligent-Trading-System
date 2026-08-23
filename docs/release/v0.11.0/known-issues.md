# v0.11.0 已知问题

| # | 问题 | 影响 | 缓解 |
|---|------|------|------|
| 1 | research/validation 面板切换丢失结果 | 结果仅存组件 state | store 层提升已立项 |
| 2 | multi_tf 本地缺 5m 基础网格时诚实返回 insufficient_data | 图表部分周期不可用 | 先 `download --timeframe 5m` 补基础网格 |
| 3 | multi_tf fields=full 载荷 ~494KB 未设上限 | 大 symbol 集响应偏大 | 默认 fields=summary 不受影响 |
| 4 | fail_under=100 覆盖率棘轮政策评估中 | CI 门禁维持最严档 | 提案：85/80 + 关键包 95+，待 owner 决策 |
| 5 | vitest fake-timers × user-event 环境死锁 | 点击类用例用 fireEvent 替代 | 已在测试注释中记录规避方式 |
| 6 | OKX DNS 在部分网络不可达 | 实盘/sandbox 连接受限 | Binance archive 兜底下载路径可用 |
