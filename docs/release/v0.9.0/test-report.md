# v0.9.0 测试报告

## 功能实测（真实 API / 端到端）
| 项 | 结果 |
|---|---|
| Binance archive 重跑（生产） | 5 组全成功：BTC 1d=2769 / BTC 1h=66397 / ETH 1h=66397 / SOL 1h=48898 / XRP 1h=22632 |
| 奇偶校验 | 新旧重叠率 100%；close 中位偏差 0.008–0.013%（容忍带 1%） |
| Bybit funding/OI | funding 90 行；OI 168 行；USD 折算 72/72 命中（偏差 0.51% < 2% 验收线） |
| Bybit futures | 交割 kline 端到端落盘（BTCUSDT-04SEP26 分区） |
| resolve_symbol 单测 | 三分支全过（-OKX 优先 / -BINANCE 次选 / bare 兜底） |
| web 接线离线验证 | BTC/USDT → -BINANCE 命中；无分区符号零行为变化 |

## 回归
- 本地定向单测：425 passed（engine/tracing/audit/paper_replay 334 + meta/validation/indicators 91）
- 全量套件：CI 门禁因存量 Mypy 违规未跑通（见 known-issues #2），专项处理
- Ruff format + lint：全仓通过（本轮完成存量清理：format 135 文件、lint 修复 210 自动 + 19 手动）

## 工具链验证
- wheel 构建成功（quantflow-0.9.0-py3-none-any.whl），SHA256 入册
