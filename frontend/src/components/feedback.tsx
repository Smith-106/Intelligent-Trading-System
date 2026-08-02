import { AlertCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  /** 错误标题（what happened） */
  title?: string;
  /** 恢复指引（why + how to fix） */
  description?: string;
  /** 技术细节（原始 error.message，折叠展示） */
  detail?: string;
  onRetry: () => void;
  retryLabel?: string;
  className?: string;
}

/**
 * RC-4 (P1-3): 错误状态 = 发生了什么 + 为什么 + 如何修复。
 * 替代原先的 "加载失败: {error.message}" + "重试" 裸模板。
 */
export function ErrorState({
  title = "数据加载失败",
  description = "无法连接到后端服务。请确认 API 服务已启动、网络正常，然后重试。",
  detail,
  onRetry,
  retryLabel = "重试连接",
  className,
}: ErrorStateProps) {
  return (
    <div className={cn("flex h-full items-center justify-center", className)}>
      <Card className="max-w-md">
        <CardContent className="pt-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
            <div>
              <p className="text-base font-semibold text-foreground">{title}</p>
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            </div>
          </div>
          {detail && (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                技术详情
              </summary>
              <p className="mt-1 break-all rounded bg-muted/40 p-2 font-mono text-xs text-muted-foreground">
                {detail}
              </p>
            </details>
          )}
          <Button onClick={onRetry} className="mt-4">
            <RefreshCw className="h-4 w-4" />
            {retryLabel}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

interface EmptyStateProps {
  /** 确认缺失（acknowledge） */
  title: string;
  /** 说明价值（explain value） */
  description?: string;
  /** 行动入口（provide action） */
  action?: React.ReactNode;
  className?: string;
}

/**
 * RC-4 (P2-12): 空状态 = 确认缺失 + 解释价值 + 提供行动。
 * 替代被动的 "暂无数据"。
 */
export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-start gap-1.5 py-6", className)}>
      <p className="text-base font-medium text-foreground">{title}</p>
      {description && <p className="max-w-prose text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
