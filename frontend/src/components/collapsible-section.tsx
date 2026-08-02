import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface CollapsibleSectionProps {
  title: string;
  /** 标题右侧附加信息（如计数 Badge） */
  aside?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * RC-2 (P2-11/P3-5): 渐进式披露 — 次要/参考性数据组默认折叠。
 * 基于原生 <details>/<summary>（无新依赖，键盘可用）。
 */
export function CollapsibleSection({
  title,
  aside,
  defaultOpen = false,
  children,
  className,
}: CollapsibleSectionProps) {
  return (
    <details
      className={cn("group rounded-lg border border-border bg-card text-card-foreground", className)}
      {...(defaultOpen ? { open: true } : {})}
    >
      <summary className="flex min-h-11 cursor-pointer select-none items-center justify-between gap-2 rounded-lg px-5 py-3 text-base font-semibold transition-colors duration-[var(--duration-fast)] hover:bg-muted/40 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          {title}
          {aside}
        </span>
        <ChevronDown
          className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-[var(--duration-fast)] ease-out-quart group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div className="border-t border-border px-5 py-4">{children}</div>
    </details>
  );
}
