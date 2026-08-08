---
title: MetaFeatures 静态因子计算：零偏移守卫 + merge_asof 方向控制
category: data
createdBy: "harvest:wave2-s3"
sourceRef: maestro-wave2-s3-20260803-20260804-040400
type: knowhow
status: active
related:
  - DOC-knowhow-rdagent-q-factor-mining-architecture
  - DOC-okx-pagination-pattern
---
# MetaFeatures 静态因子计算

## 适用场景
计算元特征（meta-features）时，需要确保不引入未来信息，且与 FeatureStore 查询协调一致。

## 设计要点

1. **零偏移守卫**：静态 guard 测试确认没有负偏移（no negative shift）
2. **merge_asof direction=backward**：使用向后合并，确保每个 bar 只看到过去的信息
3. **FeatureStore meta query end=timestamp**：查询时指定 end 时间戳，防止未来数据泄漏
4. **纯 pandas L2 计算器**：零 quantflow 导入，保持模块独立性

## 安全验证
- 静态测试断言无负偏移
- merge_asof 方向显式指定 backward（非默认）
- 时间戳边界严格：end=timestamp 而非无限

## 来源
maestro-wave2-s3 session (2026-08-04), review-findings.json R-F8..R-F10