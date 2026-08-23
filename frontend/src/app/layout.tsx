import { useEffect, useRef } from "react";
import { useUIStore } from "@/stores/ui-store";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

interface LayoutProps {
  onRefresh: () => void;
  children: React.ReactNode;
}


/** REV-022-a11y: after `key` remounts panel content the old focused node is
 * destroyed and focus falls back to <body>. Receiving focus on <main>
 * (tabIndex -1) keeps screen-reader/keyboard context at the new panel. */
function MainFocus({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  const activePanel = useUIStore((st) => st.activePanel);
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
  }, [activePanel]);
  return (
    <main
      ref={ref}
      tabIndex={-1}
      className="flex-1 overflow-y-auto p-4 outline-none md:p-6"
      id="main-content"
    >
      {/* key 变化触发重挂载动画（200ms 淡入上移） */}
      {/* RC-9 (P3-3): 超宽屏内容限宽 1920px，居中显示 */}
      <div key={activePanel} className="animate-panel-enter mx-auto max-w-[1920px]">
        {children}
      </div>
    </main>
  );
}

export function Layout({ onRefresh, children }: LayoutProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* REV-022-a11y: keyboard bypass for the sidebar tab list */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:shadow-md"
      >
        跳转到主内容
      </a>
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar onRefresh={onRefresh} />
        <MainFocus>{children}</MainFocus>
      </div>
    </div>
  );
}
