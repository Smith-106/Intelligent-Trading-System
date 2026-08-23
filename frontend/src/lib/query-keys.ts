/**
 * Odyssey-UI REV-012: single source of truth for panel → queryKey mapping.
 *
 * Previously three refresh paths drifted apart: the topbar used `[panel]`,
 * GlobalRefreshHandler hard-coded its own table with `data: [["data"]]`, and
 * the real queries use `["data-snapshot"]` / `["research-history"]` /
 * `["validation-history"]`. Net effect: the data panel could never be
 * refreshed by any global path, and the research/validation topbar buttons
 * invalidated nothing.
 */

import type { PanelId } from "@/stores/ui-store";

export const PANEL_QUERY_KEYS: Record<PanelId, string[][]> = {
  overview: [["overview"]],
  // real key in data-hub.tsx is "data-snapshot" (not the panel id)
  data: [["data-snapshot"]],
  charts: [["multi-tf"]],
  monitoring: [["monitoring"]],
  research: [["research-history"], ["strategies"]],
  validation: [["validation-history"], ["strategies"]],
  execution: [["execution"]],
  session: [["session"], ["execution"]],
  strategies: [["strategies"]],
};
