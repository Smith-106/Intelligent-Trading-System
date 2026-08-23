import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * P1 H4: Workbench 状态持久化 Store
 * 解决面板切换后表单状态蒸发问题（layout.tsx key={activePanel} 强制卸载重挂载）
 * - 使用 zustand/persist 将表单数据持久化到 localStorage
 * - 面板组件从 store 读写表单状态，切面板不丢失
 */

export interface ResearchFormState {
  strategy: string;
  symbol: string;
  capital: number;
  fee: number;
  start: string;
  end: string;
}

export interface ValidationFormState {
  strategy: string;
  symbol: string;
  method: string;
  optimize_trials: number;
  wfo_windows: number;
  capital: number;
}

export interface ChartViewState {
  symbol: string;
  timeframe: string;
  showVolume: boolean;
}

interface WorkbenchState {
  // Research form persistence
  researchForm: ResearchFormState;
  setResearchForm: (form: Partial<ResearchFormState>) => void;
  resetResearchForm: () => void;

  // Validation form persistence
  validationForm: ValidationFormState;
  setValidationForm: (form: Partial<ValidationFormState>) => void;
  resetValidationForm: () => void;

  // Chart view persistence (UI-REV016): survives panel remount
  chartView: ChartViewState;
  setChartView: (view: Partial<ChartViewState>) => void;
}

const DEFAULT_RESEARCH_FORM: ResearchFormState = {
  strategy: "trend_following",
  symbol: "BTC/USDT",
  capital: 10000,
  fee: 0.001,
  start: "2024-01-01",
  end: "",
};

const DEFAULT_CHART_VIEW: ChartViewState = {
  symbol: "BTC/USDT",
  timeframe: "1h",
  showVolume: true,
};

const DEFAULT_VALIDATION_FORM: ValidationFormState = {
  strategy: "trend_following",
  symbol: "BTC/USDT",
  method: "gate",
  optimize_trials: 50,
  wfo_windows: 4,
  capital: 10000,
};

export const useWorkbenchStore = create<WorkbenchState>()(
  persist(
    (set) => ({
      researchForm: { ...DEFAULT_RESEARCH_FORM },
      setResearchForm: (form) =>
        set((state) => ({ researchForm: { ...state.researchForm, ...form } })),
      resetResearchForm: () => set({ researchForm: { ...DEFAULT_RESEARCH_FORM } }),

      validationForm: { ...DEFAULT_VALIDATION_FORM },
      setValidationForm: (form) =>
        set((state) => ({ validationForm: { ...state.validationForm, ...form } })),
      resetValidationForm: () => set({ validationForm: { ...DEFAULT_VALIDATION_FORM } }),

      chartView: { ...DEFAULT_CHART_VIEW },
      setChartView: (view) =>
        set((state) => ({ chartView: { ...state.chartView, ...view } })),
    }),
    {
      name: "quantflow-workbench",
      partialize: (state) => ({
        researchForm: state.researchForm,
        validationForm: state.validationForm,
      }),
    },
  ),
);
