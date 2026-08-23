/**
 * Panel query shell (REV-023, hy3 roadmap #1).
 *
 * Five panels (overview/monitoring/execution/data-hub/session) carried a
 * byte-identical ~27-line shell: useQuery + loading early-return + ErrorState
 * early-return. This module owns the pieces once; each panel keeps only its
 * endpoint/interval and two one-line guards.
 */

import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import { ErrorState } from "@/components/feedback";

/** Unified loading placeholder — replaces the two inline variants. */
export function PanelLoading() {
  return (
    <div className="flex h-full items-center justify-center">
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    | ((query: any) => number | false),
): UseQueryResult<TData, Error> {
  return useQuery({ queryKey, queryFn, refetchInterval: refetchInterval as never });
}
