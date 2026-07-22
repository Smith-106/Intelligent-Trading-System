---
title: "实盘成本建模:滑点+手续费腰斩收益;永续 funding fee 不可忽略;Grafana 告警检测用户面症状"
category: execution,cost,monitoring
createdBy: manage-harvest
sourceRef: deep-research-20260718 F15
---
实盘成本与监控改进(来自 deep-research fetch 阶段):(1) 忽略交易成本(滑点+手续费)可能让年化回测收益腰斩(20%→10%),成本建模必须在回测管道中显式化;(2) 期货 funding fee 常被忽略,对持仓跨期策略会扭曲盈利性——这对 Crypto 永续合约策略尤为关键,QuantFlow 的 OKX 永续合约策略必须建模 funding rate;(3) Grafana 告警最佳实践:告警应检测用户面症状(延迟/错误/可用性)而非内部基础设施事件,后者归入低严重性非 paging 通道。来源: gainium/blog + blockchain-council + grafana alerting best-practices。fetch 阶段提取,未单独对抗验证。