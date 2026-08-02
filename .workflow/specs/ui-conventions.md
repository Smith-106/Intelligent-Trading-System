---
title: "UI Conventions"
readMode: optional
priority: medium
category: ui
keywords:
  - ui
  - design
  - color
  - typography
  - layout
  - animation
  - component
---

# UI Conventions

## Color & Theme

## Typography

## Layout & Spacing

## Motion & Animation

## Component Patterns

## Entries

<spec-entry sid="S-20260722-ui01" category="ui" keywords="design-token,spacing,typography,dark-theme" date="2026-07-22" source="ui-odyssey">

### Dark dashboard token 系统 4 轴结构

dark theme 运营 dashboard 的 `:root` 必须暴露 4 轴 token + elevation + motion，禁止散落硬编码。

- **color**: semantic bg/panel/border/text/muted + accent/accent-2/danger + `--status-go/warn/danger` + `--tone-*-fg`
- **spacing**: 4px base 6 阶 (`--sp-1..6`)，禁止裸 `24px 18px` 散落
- **font-size**: 8 阶 scale (`--fs-xs..4xl`)，禁止裸 `font-size: NNpx`
- **radius**: 3 阶 (`--radius-sm/radius/lg`)
- **elevation**: `--shadow-1/2/pop`
- **motion**: `--ease` cubic-bezier + `--dur-fast/dur`

引用一律 `var(--token)`。迁移余量见 ISS-20260722-008。

</spec-entry>

<spec-entry sid="S-20260722-ui02" category="ui" keywords="interaction,async-submit,feedback,toast,spinner" date="2026-07-22" source="ui-odyssey">

### 异步提交反馈三件套（idle→in-flight→success/error→idle）

所有 POST 提交按钮必须实现 in-flight 防重复 + 结果 toast：

- `withInFlight(node,label)` 返回 restore 回调，try/finally 调用；in-flight 期间 `node.disabled=true` + 注入 `.btn-spinner`
- 成功 → `showToast(msg, "success")`；失败 → `showToast(msg, "danger")` + 原 pill feedback
- 破坏性操作（kill switch/停止会话）额外 `holdToConfirm(node, {duration:1200})` 长按二次确认
- 轮询用 `setPollHeartbeat(stalled)` + `aria-live=polite`，失败时切 stalled 态

禁止：无反馈的静默 `setInterval + innerHTML`、可双击双提交的按钮。

</spec-entry>

<spec-entry sid="S-20260722-ui03" category="ui" keywords="accessibility,wcag,focus-visible,skip-link,reduced-motion,aria-current" date="2026-07-22" source="ui-odyssey">

### WCAG 关键 4 项最小实现

前端必须满足这 4 项无障碍基线：

1. **Bypass Blocks (2.4.1)**: body 首元素 `<a class="skip-link" href="#main-content">` + `main#main-content`，`.skip-link:focus` 滑入可视
2. **Focus Visible (2.4.7)**: 全局 `.nav-btn:focus-visible, .button:focus-visible, input:focus-visible, [tabindex]:focus-visible { outline: 2px solid var(--accent-2); outline-offset: 2px }`
3. **Reduced Motion (2.3.3)**: `@media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation/transition-duration: .01ms !important } }`
4. **Current page (9.2)**: nav-btn `aria-current="page"`，JS 面板切换时 `setAttribute/removeAttribute` 同步

待补：segment-btn 选中态 `aria-pressed`（见 ISS-20260722-009）。

</spec-entry>

<spec-entry sid="S-20260722-cg01" category="coding" keywords="numeric-render,guard,infinity,nan,toFixed,formatter" date="2026-07-22" source="ui-odyssey">

### 数值渲染必须经 guard helper，禁止裸 toFixed

所有渲染到 DOM 的数值必须经过统一 guard helper，**绕过即漏洞**。

```js
function formatMetricNumber(value, digits = 3) {
  const n = Number(value);
  if (value === null || value === undefined || Number.isNaN(n) || !Number.isFinite(n)) {
    return PLACEHOLDER;  // "待检测" / "—"
  }
  return n.toFixed(digits);
}
```

- 必须同时 guard：`null` / `undefined` / `NaN` / `Infinity` / `-Infinity`
- 任何 `Number(x).toFixed(N)` + innerHTML 路径必须改用 `formatMetricNumber(x, N)`
- 历史教训：UI Odyssey 本轮只加固了 helper 函数本身，generalize 扫描发现 `app.js:10877-10886` 会话持仓表格用裸 `toFixed` 绕过 helper，`Infinity` 透传成字面值 —— helper 加固 ≠ 所有调用点加固，必须 grep 全部 `toFixed` 调用点

</spec-entry>

<spec-entry sid="S-20260802-ui04" category="ui" keywords="responsive,table,column-hiding,progressive-disclosure,mobile,tailwind" date="2026-08-02" source="harvest:team-ui-polish-r2">

### 响应式数据表格列隐藏：`hidden sm:table-cell` 渐进披露

密集数据表格在小屏（<640px）不得强制横向滚动。次要列用 `hidden sm:table-cell` 在断点下隐藏，保留核心列始终可见：

```tsx
// th 与 td 必须对称隐藏（3 个 th 对应 3 个 td）
<th className="hidden pb-2 pr-4 sm:table-cell">文件数</th>
<td className="hidden py-2 pr-4 sm:table-cell">{sym.files}</td>
```

- 保留 4 个核心列（交易对/来源/覆盖天数/数据新鲜度）始终可见，隐藏 3 个次要列（文件数/起始/结束日期）
- `overflow-x-auto` 包裹层保留作为兜底
- 增量式改造：仅添加 class，不删除现有行为
- 来源：team-ui-polish R2 data-hub.tsx P2 修复（39→40 分）

</spec-entry>

<spec-entry sid="S-20260802-ui05" category="ui" keywords="toast,overlay,fluid-width,min,viewport,fixed-position" date="2026-08-02" source="harvest:team-ui-polish-r2">

### 固定浮层流体宽度约束：`min(420px, calc(100vw-2rem))`

`position: fixed` 浮层（toast/通知）在中间断点（375-768px）不得超出可视宽度。用 `min()` 提供容器感知尺寸，无需正式 `@container` 包裹（fixed 元素不适用 container query）：

```tsx
// ToastViewport：sm 断点起加流体约束，md 保持固定上限
"...sm:flex-col sm:max-w-[min(420px,calc(100vw-2rem))] md:max-w-[420px]"
```

- `min(420px, 100vw-2rem)` 保证浮层永不超过可用空间（两侧各留 1rem）
- 浮层是 overlay，零布局风险
- 来源：team-ui-polish R2 toast.tsx P2 修复

</spec-entry>

<spec-entry sid="S-20260802-ui06" category="ui" keywords="typography,modular-scale,major-third,heading-body-ratio,text-sm" date="2026-08-02" source="harvest:team-ui-polish-r2">

### 标题/正文字号比须对齐模数字阶（禁止跳阶）

标题与相邻正文/副标题的字号比应对齐项目模数字阶（1.25 Major Third），禁止跳过中间字阶造成视觉分离过弱：

```tsx
// 反例：18px 标题直接配 12px 副标题（跳过 14px 阶）
<p className="text-xs text-muted-foreground">  // 18:12 = 1.5，偏离字阶
// 正例：取字阶下一步 14px
<p className="text-sm text-muted-foreground">  // 18:14 ≈ 1.29，贴合 1.25 Major Third
```

- 项目字阶定义于 `globals.css`（1.25 Major Third：12/15/19/24/30...）
- 标题 `text-lg`(18px) 的副标题应取 `text-sm`(14px) 而非 `text-xs`(12px)
- 例外：紧凑品牌标签（sidebar brand tag）可有意用 `text-xs`，语义不同
- 来源：team-ui-polish R2 topbar.tsx P2 修复

</spec-entry>

