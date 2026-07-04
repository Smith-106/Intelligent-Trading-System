# 在线策略路径每根 bar 重建 DataFrame 并全窗口重算

**Source**: ANL-001 性能分析
**Tags**: performance, strategy, runtime

TradingSession.on_bar() 每收到一根 bar，策略模板（trend_following 等）将窗口重建为 DataFrame，然后对整个窗口做 rolling/ewm 计算。

实测数据：
- 空策略: 228,890 bars/s
- 单个 trend_following: 350 bars/s
- 3 个真实策略: 125.7 bars/s

瓶颈在策略层重计算，不在 session 框架或 paper 执行。优化方向：为 on_bar 添加增量路径（bounded deque + rolling state），同时保持 generate_signals(df) 作为向量化回测 API。
