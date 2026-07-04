# 运行时瓶颈在策略重计算

**Source**: ANL-001 性能洞察
**Tags**: performance, bottleneck, insight

QuantFlow 的运行时瓶颈不在 TradingSession 框架本身，也不在 PaperGateway，而在 3 类放大效应：
1. 在线策略每根 bar 全窗口重算（P0）
2. 离线验证 gate 组合放大优化成本（P0）
3. 数据/特征存储的增量写入放大（P1）

优化策略：先恢复 benchmark 可复现性，再按 P0→P1 分批优化在线策略热路径。
