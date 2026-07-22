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

