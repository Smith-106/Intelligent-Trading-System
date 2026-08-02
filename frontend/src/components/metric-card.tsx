import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type MetricTone = "default" | "go" | "warn" | "danger";

interface MetricItem {
  label: string;
  value: string | number;
  tone?: MetricTone;
}

interface FeaturedMetric extends MetricItem {
  /** 主指标下方的上下文补充（可选） */
  hint?: string;
}

function toneText(tone: MetricTone = "default"): string {
  switch (tone) {
    case "go":
      return "text-status-go";
    case "warn":
      return "text-status-warn";
    case "danger":
      return "text-status-danger";
    default:
      return "text-foreground";
  }
}

/**
 * RC-2 (P1-4): 去模板化指标布局 — 替代 4-5 个等大 MetricCard 的 AI 模板网格。
 * 1 个主指标（featured，30px 大号 + tabular-nums）+ N 个内联次级统计（18px），
 * 通过尺寸/字重/分隔线建立层级，单一卡片容器打破重复网格。
 */
export function MetricsRow({
  featured,
  items,
  className,
}: {
  featured: FeaturedMetric;
  items: MetricItem[];
  className?: string;
}) {
  return (
    <Card className={cn("overflow-hidden p-0", className)}>
      <div className="flex flex-col sm:flex-row">
        {/* 主指标 */}
        <div className="flex flex-col justify-center gap-1 border-b border-border p-5 sm:w-[34%] sm:border-b-0 sm:border-r">
          <p className="text-sm text-muted-foreground">{featured.label}</p>
          <p className={cn("text-3xl font-bold tracking-tight tabular-nums", toneText(featured.tone))}>
            {featured.value}
          </p>
          {featured.hint && <p className="text-xs text-muted-foreground">{featured.hint}</p>}
        </div>
        {/* 次级统计：移动端 2 列网格，sm+ 单行内联 + 分隔线 */}
        <div className="grid flex-1 grid-cols-2 gap-x-4 gap-y-4 p-5 sm:grid-cols-none sm:grid-flow-col sm:auto-cols-fr sm:divide-x sm:divide-border sm:p-0">
          {items.map((item) => (
            <div key={item.label} className="flex flex-col justify-center gap-1 sm:px-5">
              <p className="text-xs text-muted-foreground">{item.label}</p>
              <p className={cn("text-lg font-semibold tabular-nums", toneText(item.tone))}>
                {item.value}
              </p>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}

interface StatusRowProps {
  label: string;
  value: string | number;
  tone?: "default" | "go" | "warn" | "danger" | "muted";
}

export function StatusRow({ label, value, tone = "default" }: StatusRowProps) {
  return (
    // RC-1 (P1-1): 内容行正文 16px（原 14px），行距随之放宽
    <div className="flex items-center justify-between gap-3 py-2">
      <span className="text-base text-muted-foreground">{label}</span>
      <Badge
        variant={
          tone === "go" ? "go" : tone === "warn" ? "warn" : tone === "danger" ? "danger" : "secondary"
        }
      >
        {value}
      </Badge>
    </div>
  );
}

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export function SectionHeader({ title, subtitle, action }: SectionHeaderProps) {
  return (
    <div className="mb-4 flex items-start justify-between">
      <div>
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
