import { useUIStore } from "@/stores/ui-store";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

interface LayoutProps {
  onRefresh: () => void;
  children: React.ReactNode;
}

export function Layout({ onRefresh, children }: LayoutProps) {
  const activePanel = useUIStore((s) => s.activePanel);
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar onRefresh={onRefresh} />
        <main className="flex-1 overflow-y-auto p-4 md:p-6" id="main-content">
          {/* key 变化触发重挂载动画（200ms 淡入上移） */}
          {/* RC-9 (P3-3): 超宽屏内容限宽 1920px，居中显示 */}
          <div key={activePanel} className="animate-panel-enter mx-auto max-w-[1920px]">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
