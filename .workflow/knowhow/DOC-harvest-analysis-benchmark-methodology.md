---
title: 对标分析方法论：四级差距分级 + 外部事实源边界
category: knowhow
createdBy: harvest
sourceRef: 20260803-001-analyze
---
# 对标分析方法论：四级差距分级 + 外部事实源边界

**Source**: 20260803-001-analyze（decisions[]，locked；risk-matrix R6/R8）
**Tags**: benchmark, methodology, knowhow

可复用的外部对标分析范式（本次 benchmark-evolve session 采用）：

1. **四级差距分级**：领先/持平/落后/缺失 + 子维度细分（如执行引擎一致性持平但性能落后），避免单维度过度概括。
2. **外部事实源边界**：外部平台能力以用户调研材料为唯一事实源，不虚构外部细节；QuantFlow 侧结论一律附 file:line 代码锚点 + rg 全库扫描复核（关键否定性结论——零调用方/无绑定/未装配——全库 grep 验证而非抽查）。
3. **二手信息不确定性显式传递**：NautilusTrader 性能数字、幻方算力规模等调研材料转述均标注"未独立核验"，下游 roadmap/plan 消费时保留此边界（设 Information Boundary 专节）；方向性决策尽量不依赖外部数字精确性。
4. **范围驱动路由**：追赶议题横跨 4+ 独立子系统 → scope=large → 路由 roadmap 而非单 plan。

适用场景：任何"本系统 vs 前沿/竞品"的差距分析与演进规划。
