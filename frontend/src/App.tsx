import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Layout } from "@/app/layout";
import { OverviewPanel } from "@/panels/overview";
import { DataPanel } from "@/panels/data-hub";
import { MonitoringPanel } from "@/panels/monitoring";
import { ResearchPanel } from "@/panels/research";
import { ValidationPanel } from "@/panels/validation";
import { ExecutionPanel } from "@/panels/execution";
import { SessionPanel } from "@/panels/session";
import { StrategiesPanel } from "@/panels/strategies";
import { Toaster } from "@/components/ui/toaster";
import { GlobalRefreshHandler } from "@/components/GlobalRefreshHandler";
import { useUIStore, type PanelId } from "@/stores/ui-store";
import { useHotkeys } from "@/hooks/use-hotkeys";

const PANEL_COMPONENTS: Record<PanelId, React.ComponentType> = {
  overview: OverviewPanel,
  data: DataPanel,
  monitoring: MonitoringPanel,
  research: ResearchPanel,
  validation: ValidationPanel,
  execution: ExecutionPanel,
  session: SessionPanel,
  strategies: StrategiesPanel,
};

export function App() {
  const activePanel = useUIStore((s) => s.activePanel);
  const ActiveComponent = PANEL_COMPONENTS[activePanel];
  const queryClient = useQueryClient();
  useHotkeys();

  // P1 H1: 刷新直接调用 invalidateQueries（弃用事件总线）
  const handleRefresh = useCallback(() => {
    const panel = useUIStore.getState().activePanel;
    void queryClient.invalidateQueries({ queryKey: [panel] });
  }, [queryClient]);

  return (
    <>
      <GlobalRefreshHandler />
      <Layout onRefresh={handleRefresh}>
        <ActiveComponent />
      </Layout>
      <Toaster />
    </>
  );
}
