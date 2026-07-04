---
title: "Architecture Constraints"
readMode: required
priority: high
category: arch
keywords:
  - architecture
  - module
  - layer
  - boundary
  - dependency
  - structure
---

# Architecture Constraints

Auto-generated from project structure. Update manually as architecture evolves.

## Module Structure
- Type: single-package (quantflow/)
- Key modules:
  - quantflow/data/ — 数据获取、清洗、存储 (L1)
  - quantflow/indicators/ — 21 个因子、注册表、指标引擎 (L2)
  - quantflow/strategy/ — 策略基类、回测、优化、验证 (L3)
  - quantflow/signal/ — 信号生成、风险引擎、仓位调整 (L4)
  - quantflow/execution/ — 网关、执行引擎、订单管理 (L5)
  - quantflow/monitoring/ — Prometheus 指标、告警 (L6)
  - quantflow/common/ — 共享数据模型、事件总线、配置
  - quantflow/cli/ — Typer + Rich CLI

## Layer Boundaries
- 单向依赖：低层不导入高层
- common 是基础层（被所有层导入）
- data → common (不导入更高层)
- indicators → common (独立于 data)
- strategy → common + indicators
- signal → common
- execution → common + monitoring.metrics
- strategy.engine (TradingSession) 是编排器，导入所有层
- cli → 所有层（延迟导入以加快启动）

## Dependency Rules
- 禁止跨层直接导入（必须通过 common 或显式接口）
- TradingSession 是唯一允许跨层编排的类

## Technology Constraints
- Runtime: Python >= 3.11
- Module system: standard Python package (pyproject.toml + hatchling)
- Strict mode: mypy strict = true, python_version = "3.11"

## Entries

<spec-entry category="arch" keywords="generate_signals,on_bar,增量,向量化,双模式API" date="2026-06-13" title="保持 generate_signals(df) 为研究 API，增量 live/paper 用 on_bar" description="策略双模式 API 设计决策">
### 保持 generate_signals(df) 为研究 API，增量 live/paper 用 on_bar

保持 `generate_signals(df)` 作为向量化研究/回测 API 不变，为 live/paper 添加增量 `on_bar()` 路径。增量路径使用 bounded deque + rolling state，避免每根 bar 重建 DataFrame。必须证明增量信号与向量化信号 parity。

**来源**: ANL-001 性能分析 (context.md Decision 3 + locked constraint)
**验收**: 增量 vs 向量化信号 parity 测试存在，3 个真实策略达 2000 bars/s
</spec-entry>

<spec-entry category="arch" keywords="策略顺序,波动率突破,资金费率,动量轮动,ML集成,实施优先级" date="2026-06-13" title="新增策略实施顺序" description="从 brainstorm 收敛的四策略优先级">
### 新增策略实施顺序

新增策略按优先级排序：P1 波动率突破（复杂度低、互补性强）→ P2 资金费率（Crypto 特有、简单有效）→ P3 动量因子轮动（需多品种支持）→ P4 ML 集成（高工作量）。跨交易所套利因架构改动大优先级最低。

**来源**: brainstorm-strategies (brainstorm-output.md)
**理由**: P1/P2 复杂度低且互补性强，可并行实现
</spec-entry>

<spec-entry category="arch" keywords="W3铁律,双模式,回顾模式,渐进模式,波浪理论" date="2026-06-13" title="W3 铁律双模式" description="浪3不能最短铁律的实时处理方案">
### W3 铁律双模式：回顾强制、渐进仅检查不拒绝

回顾模式（RETROSPECTIVE）：W3 不能最短铁律强制执行，违反即拒绝浪型分类。
渐进模式（PROGRESSIVE）：W3 运行中仅检查+警告，不拒绝分类。

**来源**: brainstorm-elliott-wave C-001 决议
**理由**: Q2 滞后判定 + Q3 实时困难，需平衡严谨与可用性
</spec-entry>

<spec-entry category="arch" keywords="背离检测,浪级比较,WaveCount,DivergenceDetector" date="2026-06-13" title="DivergenceDetector 强制浪级比较" description="背离检测接口必须基于 WaveCount">
### DivergenceDetector 强制浪级比较

`DivergenceDetector.detect(wave_count: WaveCount)` — 接口接收 WaveCount 而非裸 pivots，强制 W5 vs W3 浪级比较。顶背离：W5 价格新高但 MACD 未新高。底背离：W2/W4 价格新低但 MACD 未新低。

**来源**: brainstorm-elliott-wave C-003 决议
**理由**: 波浪理论背离验证必须基于浪级，通用 pivots 接口会导致误用
</spec-entry>

<spec-entry category="arch" keywords="仓位管理,RiskEngine,PositionRequest,风控权限" date="2026-06-13" title="ScalingPosition → RiskEngine: PositionRequest 权限控制" description="分批建仓与风控引擎的交互协议">
### ScalingPosition → RiskEngine 交互协议

ScalingPositionSizer 输出 `PositionRequest`，由 RiskEngine 做最终权限控制。单笔风险 ≤2%，日最大亏损 ≤5%，月最大亏损 ≤15%。RiskEngine 可拒绝或缩减 PositionRequest。

**来源**: brainstorm-elliott-wave G-003 缺口补充
**理由**: 分批建仓模型需与风控体系解耦，RiskEngine 是最终权限门
</spec-entry>

<spec-entry category="arch" keywords="波浪理论,六层架构,规则引擎,集成方式" date="2026-06-13" title="波浪理论集成到 QuantFlow 六层架构" description="波浪理论系统设计决策">
### 波浪理论集成到 QuantFlow 六层架构，纯规则引擎

- 集成方式：集成到 QuantFlow 六层架构（非独立系统），复用现有基础设施
- 量化方式：纯规则引擎（非 ML 混合），可回测可验证，解决"千人千浪"
- 浪型表示：枚举状态机，与三大铁律规则逻辑一致
- 多时间框架：复用现有 fetcher + MTF 对齐逻辑

**来源**: brainstorm-elliott-wave D1/D2/D3 决策
**理由**: 复用六层架构降低实现成本；规则引擎确保可验证性；状态机与铁律逻辑一致
</spec-entry>
