---
title: Impeccable 10 维 UI 审计 + 持续打磨循环方法论
category: ui
createdBy: "harvest:team-ui-polish-r2"
sourceRef: 20260802-team-ui-polish-continuous
related:
  - session-20260802-team-ui-polish-full
---

# Impeccable 10 维 UI 审计 + 持续打磨循环方法论

## 适用场景

对前端 UI 做可量化、可对比、防回归的质量审计与持续改进。QuantFlow Station 前端经两轮循环从 27/40 → 37/40 → 40/40 (Perfect)。

## 10 维评分量规（每维 0-4 分，满分 40）

1. **Anti-AI Slop** — 是否避免通用 AI 模板感（等大卡片网格、青配深色、渐变文字、图标+标题冗余）
2. **Color Quality** — OKLCH 感知均匀 token、60-30-10 配比、语义角色
3. **Typography** — 模数字阶（1.25 Major Third）、clamp() 流式标题、16px 正文基线、CLS 字体度量
4. **Spacing/Layout** — 4pt 节奏、gap 用法、max-w 限宽、@container 面板
5. **Motion** — 仅 transform 动画、duration/easing token、reduced-motion 查询
6. **Interaction States** — hover/focus-visible/active/disabled 齐全、focus ring 规范
7. **Visual Hierarchy** — 眯眼测试通过、主操作明显、多维层级
8. **Responsive** — 流式断点、无横向滚动、44px 触控目标、container query
9. **Cognitive Load** — 渐进披露、动词+宾语标签、what+why+fix 错误
10. **Dark Mode** — 表面层级（越亮越高）、降饱和强调色、字重降档

## 持续打磨循环（4 角色 + GC 循环）

```
scan(8/10 维审计) → diagnose(根因分组+依赖图) → optimize(按优先级修复) → verify(前后对比+回归检查)
                                                        ↑__________________________|  (GC 循环, 最多 2 轮)
```

- **基线增量追踪**：每轮记录相对上一轮的 delta（如 37→39 +2），而非孤立分数
- **verify_passed 直接收敛**：无回归且总分 ≥ before 时 0 轮 GC
- **手术式修复原则**：高分（≥39）时仅针对诊断指定的 P2/P3 做增量改动，禁止重构/重设计破坏现有优秀设计
- **每步门禁**：TypeScript 0 错误 + vite build 成功

## 关键经验

- 分数到 39+ 后，剩余问题通常是独立一次性项（无系统性根因），可并行修复
- 验证若缺运行时测试框架，用「静态逻辑验证 + 构建门禁」替代，但须明确标注此局限并记为待办 issue
- 修复须对称（如表格 th/td 隐藏数量一致）、增量（仅加 class 不删行为）

## 来源

team-ui-polish R1/R2 sessions (2026-08-02), Impeccable scoring-guide.md
