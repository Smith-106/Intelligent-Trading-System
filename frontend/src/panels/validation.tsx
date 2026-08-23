import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type ValidationRequest, type Strategy } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/metric-card";
import { EmptyState, ErrorState } from "@/components/feedback";
import { useWorkbenchStore } from "@/stores/workbench-store";
import { useToast } from "@/hooks/use-toast";
import { Play, RefreshCw } from "lucide-react";
import { toFiniteNumber } from "@/lib/form-utils";
import { useStrategiesQuery } from "@/hooks/use-strategies-query";

/**
 * UI3-H1: badge tone mirrors the backend _validation_tone decision order —
 * "no-go" must be tested before "go" ("no-go".includes("go") is true).
 */
function decisionTone(decision: string): "go" | "danger" | "warn" {
  const d = decision.toLowerCase();
  if (d.startsWith("no") || d.includes("fail")) return "danger";
  if (d.includes("go") || d.includes("pass")) return "go";
  return "warn";
}

export function ValidationPanel() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
const { data: strategies } = useStrategiesQuery();

  // Odyssey-UI REV-012: surface loading/error instead of an empty state.
  const {
    data: history,
    refetch: refetchHistory,
    isLoading: historyLoading,
    isError: historyError,
    error: historyErr,
  } = useQuery({
    queryKey: ["validation-history"],
    queryFn: () => api.validationHistory(12),
    refetchInterval: 60000,
  });

  // P1 H4: 从 Zustand store 读取表单状态（切面板不丢失）
  const { validationForm, setValidationForm } = useWorkbenchStore();
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.validate(validationForm as ValidationRequest),
    onSuccess: (data) => {
      setResult(data as unknown as Record<string, unknown>);
      toast({ title: "验证完成", description: "防过拟合验证已完成。" });
      queryClient.invalidateQueries({ queryKey: ["validation-history"] });
      // Odyssey-UI REV-012: monitoring counters (validation_runs) freshness.
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    },
    onError: (error) => {
      toast({
        title: "验证失败",
        description: error instanceof Error ? error.message : "未知错误",
        variant: "destructive",
      });
    },
  });

  const historyItems = Array.isArray(history) ? history : (history as { items?: unknown[] })?.items ?? [];

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div>
        <h2 className="text-panel-title font-bold">策略验证</h2>
        <p className="text-sm text-muted-foreground">防过拟合验证管道</p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Form */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">验证配置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label htmlFor="validation-strategy" className="mb-1 block text-xs text-muted-foreground">策略</label>
              <select
              id="validation-strategy"
                value={validationForm.strategy}
                onChange={(e) => setValidationForm({ strategy: e.target.value })}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {strategies?.map((s: Strategy) => (
                  <option key={s.strategy_id} value={s.strategy_id}>
                    {s.title}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="validation-symbol" className="mb-1 block text-xs text-muted-foreground">交易对</label>
                <Input
              id="validation-symbol"
                  value={validationForm.symbol}
                  onChange={(e) => setValidationForm({ symbol: e.target.value })}
                />
              </div>
              <div>
                <label htmlFor="validation-method" className="mb-1 block text-xs text-muted-foreground">验证方法</label>
                <select
              id="validation-method"
                  value={validationForm.method}
                  onChange={(e) => setValidationForm({ method: e.target.value })}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="gate">Gate (CPCV+DSR+PBO+WFO)</option>
                  <option value="cpcv">CPCV</option>
                  <option value="wfo">WFO</option>
                  <option value="pbo">PBO</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="validation-trials" className="mb-1 block text-xs text-muted-foreground">优化次数</label>
                <Input
              id="validation-trials"
                  type="number"
                  min="1"
                  value={validationForm.optimize_trials}
                  onChange={(e) => setValidationForm({ optimize_trials: toFiniteNumber(e.target.value, 50) })}
                />
              </div>
              <div>
                <label htmlFor="validation-wfo" className="mb-1 block text-xs text-muted-foreground">WFO 窗口数</label>
                <Input
              id="validation-wfo"
                  type="number"
                  min="1"
                  value={validationForm.wfo_windows}
                  onChange={(e) => setValidationForm({ wfo_windows: toFiniteNumber(e.target.value, 5) })}
                />
              </div>
            </div>

            <div>
              <label htmlFor="validation-capital" className="mb-1 block text-xs text-muted-foreground">初始资金</label>
              <Input
              id="validation-capital"
                type="number"
                min="1"
                value={validationForm.capital}
                onChange={(e) => setValidationForm({ capital: toFiniteNumber(e.target.value) })}
              />
            </div>

            <Button
              className="w-full"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              aria-busy={mutation.isPending}
            >
              <Play className="mr-2 h-4 w-4" />
              {mutation.isPending ? "验证中..." : "启动验证"}
            </Button>

            {mutation.isError && (
              <p className="text-sm text-destructive" role="alert">错误: {mutation.error.message}</p>
            )}
          </CardContent>
        </Card>

        {/* Result */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">验证结果</CardTitle>
          </CardHeader>
          <CardContent>
            {mutation.isPending ? (
              <div className="py-8 text-center text-sm text-muted-foreground">验证中...</div>
            ) : result ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <Badge variant={decisionTone(String(result.decision))}>
                    {String(result.decision)}
                  </Badge>
                  <Badge variant="outline">{String(result.method)}</Badge>
                </div>

                {typeof result.reason === "string" && result.reason && (
                  <div>
                    <SectionHeader title="原因" />
                    <p className="text-sm text-muted-foreground">{result.reason}</p>
                  </div>
                )}

                <div>
                  <SectionHeader title="验证指标" />
                  <div className="grid grid-cols-2 gap-3 rounded-lg bg-muted/30 p-3">
                    {(result.metrics
                      ? Object.entries(result.metrics as Record<string, unknown>)
                      : []
                    ).map(([key, value]) => (
                      <div key={key}>
                        <p className="text-xs text-muted-foreground">{key}</p>
                        <p className="text-sm font-semibold">
                          {typeof value === "number" ? value.toFixed(4) : String(value)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-muted-foreground">
                配置参数后启动验证
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* History — RC-4 (P2-12): 空状态 = 确认 + 价值 + 行动 */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">验证历史</CardTitle>
            <Button variant="outline" size="sm" onClick={() => refetchHistory()}>
              <RefreshCw className="mr-2 h-3 w-3" />
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {historyError ? (
            <ErrorState
              detail={historyErr instanceof Error ? historyErr.message : "加载验证历史失败"}
              onRetry={() => refetchHistory()}
            />
          ) : historyLoading ? (
            <div className="py-6 text-center text-sm text-muted-foreground">加载中...</div>
          ) : historyItems.length === 0 ? (
            <EmptyState
              title="暂无验证记录"
              description="运行第一次防过拟合验证后，验证的历史记录将显示在这里。建议保留最近的 5-10 次验证记录以进行审计。"
            />
          ) : (
            <div className="space-y-2">
              {historyItems.slice(0, 6).map((item: Record<string, unknown>, i: number) => {
                const summary = (item.summary ?? {}) as Record<string, unknown>;
                const decision = String(summary.outcome_label ?? summary.decision ?? "unknown");
                return (
                  <div key={(item.record_id as string) ?? i} className="rounded-lg border p-3">
                    <div className="flex items-center gap-2">
                      <Badge variant={decisionTone(decision)} className="text-xs">
                        {decision}
                      </Badge>
                      <Badge variant="outline" className="text-xs">
                        {String(summary.method_label ?? summary.method ?? "unknown")}
                      </Badge>
                      {typeof item.created_at === "string" && (
                        <span className="ml-auto text-xs text-muted-foreground">
                          {new Date(item.created_at).toLocaleDateString("zh-CN")}
                        </span>
                      )}
                    </div>
                    {typeof summary.reason === "string" && summary.reason && (
                      <p className="mt-2 text-xs text-muted-foreground">{summary.reason}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
