import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface LiveWarningBannerProps {
  mode: string;
  className?: string;
}

/**
 * P0 H3: 实盘模式持久警告条
 * - mode === "live": 常驻 danger 色调警告
 * - mode !== "live": 完全隐藏
 */
export function LiveWarningBanner({ mode, className }: LiveWarningBannerProps) {
  if (mode !== "live") return null;

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4",
        className,
      )}
      role="alert"
      aria-live="polite"
    >
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
      <div>
        <p className="font-semibold text-destructive">实盘交易警告</p>
        <p className="mt-1 text-sm text-destructive/90">
          您即将使用<span className="font-semibold">真实资金</span>进行交易。
          请确认策略已通过验证门禁、风险控制参数已设置、仓位管理符合预期。
        </p>
      </div>
    </div>
  );
}
