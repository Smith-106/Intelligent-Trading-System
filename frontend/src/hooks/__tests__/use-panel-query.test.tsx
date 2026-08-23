/**
 * use-panel-query 面板查询壳最小测试（前端测试基建首测）。
 *
 * 覆盖面板统一的两个早退守卫的渲染契约：
 * 1. PanelLoading：渲染「加载中...」占位文本；
 * 2. PanelError：标题包含调用方 context（`${context}加载失败`），
 *    点击重试按钮触发传入的 onRetry（测试中以 refetch mock 充当，
 *    生产中即 useQuery().refetch）。
 *
 * usePanelQuery 本体是 useQuery 的薄包装（透传 queryKey/queryFn/interval），
 * 行为由 @tanstack/react-query 保证，不在此重复测试。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PanelError, PanelLoading } from "@/hooks/use-panel-query";

describe("PanelLoading", () => {
  it("渲染「加载中...」占位文本", () => {
    render(<PanelLoading />);

    expect(screen.getByText("加载中...")).toBeInTheDocument();
  });
});

describe("PanelError", () => {
  it("标题含 context 与失败详情，点击重试触发 refetch", async () => {
    const user = userEvent.setup();
    const refetch = vi.fn(async () => undefined);

    render(<PanelError context="行情数据" error={new Error("ECONNREFUSED")} onRetry={refetch} />);

    // 标题 = `${context}加载失败`
    expect(screen.getByText("行情数据加载失败")).toBeInTheDocument();

    // 技术详情折叠区携带原始 error.message
    expect(screen.getByText("ECONNREFUSED")).toBeInTheDocument();

    // 重试按钮触发 onRetry（生产中即 refetch mock）
    await user.click(screen.getByRole("button", { name: "重试连接" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
