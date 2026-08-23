/**
 * Panel query shell (REV-023, hy3 roadmap #1).
 *
 * Five panels (overview/monitoring/execution/data-hub/session) carried a
 * byte-identical ~27-line shell: useQuery + loading early-return + ErrorState
 * early-return. This module owns the pieces once; each panel keeps only its
 * endpoint/interval and two one-line guards.
 */

import { useQuery } from "@tanstack/react-query";
import type { Query, UseQueryResult } from "@tanstack/react-query";

import { ErrorState } from "@/components/feedback";

/** Unified loading placeholder — replaces the two inline variants. */
export function PanelLoading() {
  return (
    /* REV-025-M4: the layout key-div has no height chain, so h-full
       collapsed to content height and the text hugged the panel top. */
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="text-sm text-muted-foreground">加载中...</div>
    </div>
  );
}

/** Standard panel error guard: what + why + fix via the shared ErrorState. */
export function PanelError({
  context,
  error,
  onRetry,
}: {
  context: string;
  error: Error;
  onRetry: () => void;
}) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <ErrorState
        title={`${context}加载失败`}
        description="无法连接到后端服务。请确认 Station API 已启动后重试。"
        detail={error.message}
        onRetry={onRetry}
      />
    </div>
  );
}

/** Thin useQuery wrapper pinning the standard shape (queryKey/queryFn/interval). */
export function usePanelQuery<TData>(
  queryKey: readonly unknown[],
  queryFn: () => Promise<TData>,
  refetchInterval?:
    | number
    // hy3 RV-008：用 react-query 的 Query 类型收窄 any 逃逸；泛型绑定到本面板的 TData，
    // 以便调用方函数式 interval 直接读取 query.state.data 字段（如 session 的 running）。
    | ((query: Query<TData, Error>) => number | false),
): UseQueryResult<TData, Error> {
  // refetchInterval 现已类型正确，无需 as never 双重断言。
  return useQuery({ queryKey, queryFn, refetchInterval });
}
