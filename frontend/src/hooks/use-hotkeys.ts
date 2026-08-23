/**
 * 全局键盘快捷键：
 * - Alt+1..8（含 Numpad1..8）：切换 8 个面板（顺序 = NAV_ITEMS 顺序）
 * - Alt+R：刷新当前面板（通过 GlobalRefreshHandler 的 window.__quantflow_refresh__）
 *
 * 输入态（input/textarea/select/contentEditable）忽略，不拦截表单输入。
 */
import { useEffect } from "react";
import { useUIStore, type PanelId } from "@/stores/ui-store";

/** 与 sidebar NAV_ITEMS 顺序一致 */
const PANEL_ORDER: PanelId[] = [
  "overview",
  "data",
  "charts",
  "monitoring",
  "research",
  "validation",
  "execution",
  "session",
  "strategies",
];

const DIGIT_CODES: Record<string, number> = {
  Digit1: 1, Digit2: 2, Digit3: 3, Digit4: 4,
  Digit5: 5, Digit6: 6, Digit7: 7, Digit8: 8, Digit9: 9,
  Numpad1: 1, Numpad2: 2, Numpad3: 3, Numpad4: 4,
  Numpad5: 5, Numpad6: 6, Numpad7: 7, Numpad8: 8, Numpad9: 9,
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

export function useHotkeys(): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return;
      if (isTypingTarget(e.target)) return;

      const panelIndex = DIGIT_CODES[e.code];
      if (panelIndex !== undefined) {
        e.preventDefault(); // 防止浏览器 Alt 菜单激活
        const panel = PANEL_ORDER[panelIndex - 1];
        if (panel) {
          useUIStore.getState().setActivePanel(panel);
        }
        return;
      }

      if (e.code === "KeyR") {
        e.preventDefault();
        // P1 H1: 通过 GlobalRefreshHandler 暴露的全局方法刷新
        const refresh = (window as unknown as Record<string, { current?: () => void }>).__quantflow_refresh__;
        if (refresh?.current) {
          refresh.current();
        }
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
}
