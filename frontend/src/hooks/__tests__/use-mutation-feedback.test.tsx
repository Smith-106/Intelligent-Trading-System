/**
 * useMutationFeedback 统一变更反馈 Hook 最小测试（前端测试基建首测）。
 *
 * 覆盖 REV-023-RV2 契约的三个关键行为：
 * 1. 成功路径：notice.kind === "success"，onSuccess.description 以
 *    「函数式」收到 mutation 结果 data；inlineMs 到期后 notice 自清。
 * 2. 错误路径：notice.kind === "error" 且「常驻」——远超任何 inlineMs 的
 *    时间推进后仍在，只能被下一次尝试或 dismissNotice 清除。
 *
 * 说明：
 * - Hook 内部经 useToast 产生 toast 副作用（模块级 store），无需渲染
 *   Toaster，不影响断言；
 * - react-query 的 mutation 在 retry 关闭下不依赖定时器，与 fake timers 兼容。
 */

import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { useMutationFeedback } from "@/hooks/use-mutation-feedback";

/** 每个用例独立的 QueryClient + Provider 包装（隔离缓存，关闭 retry 避免定时器干扰）。 */
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useMutationFeedback", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("成功后 notice 为 success 且函数式 description 收到 data，inlineMs 后自清", async () => {
    // 函数式 description：以 mutation 结果拼装 detail（如 rows_saved）
    const description = vi.fn((data: { rows: number }) => `已写入 ${data.rows} 行`);

    const { result } = renderHook(
      () =>
        useMutationFeedback<{ rows: number }, { id: number }>({
          mutationFn: async ({ id }) => ({ rows: id * 2 }),
          onSuccess: { title: "下载完成", description },
          inlineMs: 1000,
        }),
      { wrapper: createWrapper() },
    );

    // 初始无 notice
    expect(result.current.notice).toBeNull();

    await act(async () => {
      result.current.mutate({ id: 21 });
    });

    // 函数式 description 收到的是完整结果对象 data（而非字符串）
    expect(description).toHaveBeenCalledTimes(1);
    expect(description).toHaveBeenCalledWith({ rows: 42 });

    expect(result.current.notice).toEqual({
      kind: "success",
      title: "下载完成",
      detail: "已写入 42 行",
    });

    // inlineMs 到期前仍在，到期后自动清除（fake timers 推进）
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(result.current.notice).toEqual({
      kind: "success",
      title: "下载完成",
      detail: "已写入 42 行",
    });

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.notice).toBeNull();
  });

  it("失败后 notice 为 error 且常驻，不随时间自动清除", async () => {
    const { result } = renderHook(
      () =>
        useMutationFeedback<void, void>({
          mutationFn: async () => {
            throw new Error("boom");
          },
          onError: { title: "启动失败" },
        }),
      { wrapper: createWrapper() },
    );

    await act(async () => {
      result.current.mutate();
    });

    // 错误 notice 携带 title 与兜底的 error.message 详情
    const errorNotice = { kind: "error", title: "启动失败", detail: "boom" };
    expect(result.current.notice).toEqual(errorNotice);

    // 推进远超默认 inlineMs(8000ms) 的时间：错误常驻，不被自清
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(result.current.notice).toEqual(errorNotice);
  });
});
