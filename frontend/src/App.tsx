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
import { ChartsPanel } from "@/panels/charts";
import { Toaster } from "@/components/ui/toaster";
import { GlobalRefreshHandler } from "@/components/GlobalRefreshHandler";
import { useUIStore, type PanelId } from "@/stores/ui-store";
import { useHotkeys } from "@/hooks/use-hotkeys";
import { PANEL_QUERY_KEYS } from "@/lib/query-keys";

const PANEL_COMPONENTS: Record<PanelId, React.ComponentType> = {
  overview: OverviewPanel,
  data: DataPanel,
  charts: ChartsPanel,
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

  // Odyssey-UI REV-012: refresh keys come from the shared PANEL_QUERY_KEYS
  // table — `[panel]` never matched the real query keys (data-snapshot /
  // research-history / validation-history), so these buttons were no-ops.
  const handleRefresh = useCallback(() => {
    const panel = useUIStore.getState().activePanel;
    PANEL_QUERY_KEYS[panel].forEach((key) => {
      void queryClient.invalidateQueries({ queryKey: key });
    });
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
