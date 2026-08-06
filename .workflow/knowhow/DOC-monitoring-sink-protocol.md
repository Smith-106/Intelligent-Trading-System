---
title: MonitoringSink Protocol 扩展：Protocol/Null/Default 三层解耦
category: architecture
createdBy: "harvest:wave3-s4"
sourceRef: maestro-wave3-s4-20260804-20260804-054608
---
# MonitoringSink Protocol 扩展模式

## 适用场景
交易引擎需要向监控系统报告策略 PnL 等运行指标，但监控层（L6）与策略层（L3）之间需保持解耦，避免循环依赖。

## 设计要点

1. **Protocol 定义接缝**：通过 `typing.Protocol` 定义 MonitoringSink 接口
2. **Null 默认实现**：默认使用 Null sink（无操作），向前兼容
3. **Default 实现**：提供默认监控实现（记录到本地或标准输出）
4. **L3/L4 保持零 L6 导入**：协议层不导入任何 L6 监控模块
5. **纯附加可观测性**：engine.py 调用 `self._sink.record_strategy_pnl` 不改变控制流

## 架构优势
- 策略层无需感知监控实现细节
- 新监控接入只需实现 Protocol，无需修改引擎
- 默认 Null 保证零配置即可运行
- 附加式设计：sink 失败不影响交易循环

## 来源
maestro-wave3-s4 session (2026-08-04), review-findings.json R-F9..R-F12