---
title: Anti-AI-slop 设计信号清单（QuantFlow Station）
category: ui
createdBy: "harvest:team-ui-polish-r2"
sourceRef: 20260802-team-ui-polish-continuous
related:
  - session-20260802-team-ui-polish-full
type: knowhow
status: active
---
# Anti-AI-slop 设计信号清单（QuantFlow Station）

## 适用场景

判断前端 UI 是否摆脱「通用 AI 生成模板感」，建立有意图的差异化设计。QuantFlow Station 达成 Zero AI tells (Anti-AI Slop 4/4)。

## 干净设计信号（Clean Design Signals）

- **OKLCH 色彩 token 贯穿** — 无「青色配深色背景」、无渐变文字；感知均匀 OKLCH，统一 chroma/saturation 比
- **MetricsRow 去模板** — 用「1 featured + N inline」指标行替代「等大卡片网格」模板（见独立条目）
- **有意图的字体** — Space Grotesk + CLS 匹配的 fallback 度量（font-display swap + 预补偿）
- **暗色表面层级** — 越亮 = 越高深度 + 字重降档（600→500, 700→600 光学补偿）
- **focus ring 达规范** — 2px solid accent + offset，3:1+ 对比
- **触控目标 ≥44px 一致** — 按钮 h-11、导航项 min-h-11、图标按钮 h-11 w-11
- **渐进披露** — CollapsibleSection 收纳次要/技术信息
- **错误/空态遵循 what+why+fix** — 标题(what) + 描述(why) + 重试操作(fix)

## 常见 AI slop 特征（须避免）

- 等大卡片网格铺满仪表盘（无主次）
- 青/紫渐变配深色背景
- 渐变文字标题
- 每个卡片都「图标 + 标题 + 描述」三段式冗余
- 通用圆角 + 通用阴影 + 通用间距（无设计系统 token）
- 装饰性元素无信息价值

## 检测要点

眯眼测试（squint test）：模糊后仍能看出主操作与层级 = 通过。所有颜色走 `var(--token)`，无散落硬编码。

## 来源

team-ui-polish R2 scan-report.md (2026-08-02), Impeccable anti-patterns.md
