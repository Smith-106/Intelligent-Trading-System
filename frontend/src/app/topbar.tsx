import { PANEL_LABELS, useUIStore } from "@/stores/ui-store";
import { RefreshCw, Sun, Moon, Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface TopbarProps {
  onRefresh: () => void;
}

export function Topbar({ onRefresh }: TopbarProps) {
  const activePanel = useUIStore((s) => s.activePanel);
  const theme = useUIStore((s) => s.theme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);

  return (
    <header className="flex h-14 items-center justify-between border-b border-border px-4 md:px-6">
      <div className="flex items-center gap-3">
        {/* 移动端汉堡按钮 */}
        <Button
          variant="ghost"
          size="sm"
          className="md:hidden"
          onClick={() => setSidebarOpen(true)}
          aria-label="打开导航"
        >
          <Menu className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-lg font-semibold text-foreground">业务工作台</h1>
          <p className="hidden text-sm text-muted-foreground sm:block">
            统一查看系统状态、研究回测、验证门禁和运行中的交易会话。
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Badge variant="secondary">{PANEL_LABELS[activePanel]}</Badge>
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "切换到亮色主题" : "切换到暗色主题"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
        <Button variant="ghost" size="sm" onClick={onRefresh}>
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          刷新
        </Button>
      </div>
    </header>
  );
}
