/**
 * CopyableText 组件最小测试（前端测试基建首测）。
 *
 * 覆盖三条行为线（对应组件 REV-023 设计意图）：
 * 1. 渲染：优先显示 display 摘要，title 属性保留完整 value；
 *    未传 display 时回退为完整 value。
 * 2. 点击复制：navigator.clipboard.writeText 必须以「完整 value」被调用，
 *    而非截断的 display（jsdom 无剪贴板，用 mock 替身）。
 * 3. 「已复制」反馈：sr-only status 文本出现，2 秒后自动消失（fake timers）。
 */

import { render, screen, act, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import { CopyableText } from "@/components/copyable-text";

/** 给 jsdom 缺失的 navigator.clipboard 挂一个 writeText mock，返回该 mock 供断言。 */
function stubClipboard(): Mock<(value: string) => Promise<void>> {
  // 参数名带下划线前缀：仅为推断签名类型，实现中不使用
  const writeText = vi.fn((_value: string) => Promise.resolve());
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  return writeText;
}

describe("CopyableText", () => {
  let writeText: Mock<(value: string) => Promise<void>>;

  beforeEach(() => {
    writeText = stubClipboard();
    // 复制成功后的 2 秒回退由 setTimeout 驱动，用 fake timers 精确控制
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("优先渲染 display 摘要，title 提示保留完整 value", () => {
    render(<CopyableText value="sess-full-id-1234" display="sess…1234" />);

    const button = screen.getByRole("button");
    expect(button).toHaveTextContent("sess…1234");
    expect(button).not.toHaveTextContent("sess-full-id-1234");
    expect(button).toHaveAttribute("title", "复制：sess-full-id-1234");
  });

  it("未传 display 时直接显示完整 value", () => {
    render(<CopyableText value="plain-value-99" />);

    expect(screen.getByRole("button")).toHaveTextContent("plain-value-99");
  });

  it("点击后以完整 value 调用 clipboard.writeText，「已复制」出现并在 2s 后自动消失", async () => {
    render(<CopyableText value="full-value-abc-999" display="full…999" />);

    // 点击前无已复制状态
    expect(screen.getByRole("status")).toHaveTextContent(/^$/);

    // 说明：此处用同步 fireEvent 而非 user-event —— 本环境（vitest 4 fake timers + jsdom）
    // 下 user-event 内部定时器等待与假时钟互等导致超时；fireEvent 直接触发 onClick，
    // 对「点击后行为」的断言完全等效。
    fireEvent.click(screen.getByRole("button"));

    // 写入剪贴板的是完整值，而非截断的 display（writeText 在点击时同步调用）
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText).toHaveBeenCalledWith("full-value-abc-999");

    // 冲刷微任务：让 writeText().then 的成功回调（setCopied）落地
    await act(async () => {});

    // sr-only 的 role=status 文本翻转
    expect(screen.getByRole("status")).toHaveTextContent("已复制到剪贴板");

    // 前进 2 秒：状态自动清除（回到空文本）
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^$/);
  });
});
