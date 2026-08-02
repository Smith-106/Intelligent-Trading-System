import { create } from "zustand";

export type PanelId =
  | "overview"
  | "data"
  | "monitoring"
  | "research"
  | "validation"
  | "execution"
  | "session"
  | "strategies";

export const PANEL_LABELS: Record<PanelId, string> = {
  overview: "总览",
  data: "数据中心",
  monitoring: "监控运维",
  research: "研究回测",
  validation: "验证门禁",
  execution: "执行工作台",
  session: "交易会话",
  strategies: "策略目录",
};

interface UIState {
  activePanel: PanelId;
  setActivePanel: (panel: PanelId) => void;
  /** 暗/亮主题（持久化到 localStorage 'quantflow-theme'，默认 dark） */
  theme: "dark" | "light";
  toggleTheme: () => void;
  /** 移动端侧栏抽屉状态 */
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
}

const THEME_STORAGE_KEY = "quantflow-theme";

function initialTheme(): "dark" | "light" {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export const useUIStore = create<UIState>((set, get) => ({
  activePanel: "overview",
  setActivePanel: (panel) => set({ activePanel: panel }),

  theme: initialTheme(),
  toggleTheme: () => {
    const next = get().theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* storage 不可用时仅切换内存状态 */
    }
    document.documentElement.classList.toggle("dark", next === "dark");
    set({ theme: next });
  },

  sidebarOpen: false,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
}));
