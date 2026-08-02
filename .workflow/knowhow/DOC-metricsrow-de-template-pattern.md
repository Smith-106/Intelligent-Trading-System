---
title: MetricsRow 去模板模式 — featured + inline 指标行
category: ui
createdBy: "harvest:team-ui-polish-r2"
sourceRef: 20260802-team-ui-polish-continuous
---
# MetricsRow 去模板模式 — featured + inline 指标行

## 适用场景

仪表盘指标展示去「等大卡片网格」模板化，建立有主次的视觉层级。QuantFlow Station 用此模式替代 4-5 个等大 MetricCard，移除 20+ 处图标+标题冗余。

## 问题：等大卡片网格的模板感

```tsx
// 反模式：N 个等大卡片铺成网格，无主次，典型 AI 模板指纹
<grid cols={4}>
  {metrics.map(m => <MetricCard icon={...} title={...} value={...} />)}
</grid>
```

## 方案：1 featured + N inline

```tsx
// MetricsRow：1 个突出主指标 + N 个内联次要指标
<MetricsRow
  featured={{ label: "总资产", value: "$123,456", delta: "+2.3%" }}
  inline={[
    { label: "现金", value: "$45,000" },
    { label: "市值", value: "$78,456" },
    { label: "未平仓", value: "3" },
  ]}
/>
```

- **featured** 占更大字号/权重，承载用户最关心的核心指标
- **inline** 用紧凑标签:值对，次要信息一行排开
- 移除每张卡片的图标 + 标题 + 描述三段式冗余

## 收益

- 视觉层级清晰（眯眼测试可辨主次）→ Visual Hierarchy 4/4
- 信息密度提升，认知负载下降 → Cognitive Load +1
- 摆脱通用 AI 模板指纹 → Anti-AI Slop 4/4

## 配套

- 错误/空态用 ErrorState/EmptyState（feedback.tsx）
- 次要技术信息用 CollapsibleSection 渐进披露

## 来源

team-ui-polish R1/R2 (2026-08-02), frontend/src/components/metric-card.tsx
