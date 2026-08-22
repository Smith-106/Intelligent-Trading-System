import { useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUIStore } from "@/stores/ui-store";
import { PANEL_QUERY_KEYS } from "@/lib/query-keys";

/**
 * P1 H1: 全局刷新处理器（弃用事件总线）
 * - Ctrl+R / Alt+R: 刷新当前面板
 * - 暴露 window.__quantflow_refresh__ 供顶栏按钮调用
 * - 纯逻辑组件，不渲染 DOM
 */
export function GlobalRefreshHandler() {
  const queryClient = useQueryClient();
  const activePanel = useUIStore((state) => state.activePanel);

  const handleRefreshAll = useCallback(() => {
    Object.values(PANEL_QUERY_KEYS).forEach((queryKeys) => {
      queryKeys.forEach((key) => {
        void queryClient.invalidateQueries({ queryKey: key });
      });
    });
  }, [queryClient]);

  const handleRefreshCurrent = useCallback(() => {
    const keys = PANEL_QUERY_KEYS[activePanel];
    if (keys) {
      keys.forEach((key) => {
        void queryClient.invalidateQueries({ queryKey: key });
      });
    }
  }, [activePanel, queryClient]);

  // 注册全局刷新快捷键（替代原有的 quantflow:refresh 事件）
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+R / Cmd+R: 刷新所有
      if ((e.ctrlKey || e.metaKey) && e.key === "r") {
        e.preventDefault();
        handleRefreshAll();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleRefreshAll]);

  // 暴露全局方法供顶栏按钮调用
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__quantflow_refresh__ = {
      all: handleRefreshAll,
      current: handleRefreshCurrent,
    };
    return () => {
      delete (window as unknown as Record<string, unknown>).__quantflow_refresh__;
    };
  }, [handleRefreshAll, handleRefreshCurrent]);

  return null;
}
