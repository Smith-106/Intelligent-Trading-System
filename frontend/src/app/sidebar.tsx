import { cn } from "@/lib/utils";
import { PANEL_LABELS, useUIStore, type PanelId } from "@/stores/ui-store";
import {
  LayoutDashboard,
  Database,
  ChartCandlestick,
  Activity,
  FlaskConical,
  ShieldCheck,
  Terminal,
  Radio,
  BookOpen,
} from "lucide-react";

const NAV_ITEMS: Array<{ id: PanelId; icon: React.ComponentType<{ className?: string }> }> = [
  { id: "overview", icon: LayoutDashboard },
  { id: "data", icon: Database },
  { id: "charts", icon: ChartCandlestick },
  { id: "monitoring", icon: Activity },
  { id: "research", icon: FlaskConical },
  { id: "validation", icon: ShieldCheck },
  { id: "execution", icon: Terminal },
  { id: "session", icon: Radio },
  { id: "strategies", icon: BookOpen },
];

export function Sidebar() {
  const activePanel = useUIStore((s) => s.activePanel);
  const setActivePanel = useUIStore((s) => s.setActivePanel);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);

  const handlePanelClick = (id: PanelId) => {
    setActivePanel(id);
    // 移动端选择面板后自动关闭抽屉
    setSidebarOpen(false);
  };

  return (
    <>
      {/* 移动端遮罩层 */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-scrim/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside
        className={cn(
          // RC-6: 抽屉滑动使用动效令牌（400ms ease-out-quart）
          "flex h-screen w-60 flex-col border-r border-border bg-card transition-transform duration-[var(--duration-slow)] ease-out-quart",
          // <md: fixed 抽屉，受 sidebarOpen 控制；md+: 静态侧栏
          "fixed inset-y-0 left-0 z-50 md:static md:z-auto md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
      {/* Brand */}
      <div className="flex items-center gap-3 px-4 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary font-bold text-primary-foreground text-sm">
          QF
        </div>
        <div>
          <div className="text-sm font-semibold text-foreground">QuantFlow Station</div>
          <div className="text-xs text-muted-foreground">Crypto 交易平台</div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-2" aria-label="面板切换">
        {NAV_ITEMS.map(({ id, icon: Icon }, index) => {
          const isActive = id === activePanel;
          return (
            <button
              key={id}
              onClick={() => handlePanelClick(id)}
              title={`${PANEL_LABELS[id]} (Alt+${index + 1})`}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                // RC-3: 导航项 ≥44px 触控目标（min-h-11）
                "flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors duration-[var(--duration-fast)]",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {PANEL_LABELS[id]}
            </button>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t border-border px-4 py-3">
        <span className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
          v0.3.0
        </span>
      </div>
      </aside>
    </>
  );
}
