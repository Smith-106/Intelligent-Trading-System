# v0.9.0 已知问题

| # | 问题 | 影响 | 缓解 |
|---|------|------|------|
| 1 | 本机 OKX DNS 不可达 | OKX 存量 `-OKX` 重跑待网络恢复 | 迁移手册提供命令模板；resolver 过渡期回落 bare |
| 2 | CI Mypy strict 存量违规 ~420 处（CI 自 v0.7.x 起 SHA 损坏从未真正运行，历史堆积） | CI quality 门红 | 与本次功能无关；专项清理会话处理 |
| 3 | CI pip-audit / pytest 全量门未在本轮验证 | 同上 | 同上 |
| 4 | Binance 月度归档右端缺口（当前月不完整） | 新分区止于最后完整月 | 下月归档发布后增量补齐 |
| 5 | web API payload 未显式外露 store_symbol 字段 | provenance 仅日志 | 后续小步增强 |
| 6 | `data_source` 标签体系二元（okx/demo），多所时代失义 | 标注粒度粗 | P5 跟随项 |
