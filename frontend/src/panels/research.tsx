import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { PanelLoading } from "@/hooks/use-panel-query";
import { api, type ResearchRequest, type ResearchResult, type Strategy } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/metric-card";
import { EmptyState, ErrorState } from "@/components/feedback";
import { useWorkbenchStore } from "@/stores/workbench-store";
import { useToast } from "@/hooks/use-toast";
import { Play, RefreshCw } from "lucide-react";
import { fmtDateTime } from "@/lib/format";
import { toFiniteNumber } from "@/lib/form-utils";
import { useStrategiesQuery } from "@/hooks/use-strategies-query";

export function ResearchPanel() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
const { data: strategies } = useStrategiesQuery();

  // Odyssey-UI REV-012: surface loading/error instead of masquerading
  // failures as an empty state ("暂无研究记录").
  const {
    data: history,
    refetch: refetchHistory,
    isLoading: historyLoading,
    isError: historyError,
    error: historyErr,
  } = useQuery({
    queryKey: ["research-history"],
    queryFn: () => api.researchHistory(12),
    refetchInterval: 60000,
  });

  // P1 H4: 从 Zustand store 读取表单状态（切面板不丢失）
  const { researchForm, setResearchForm } = useWorkbenchStore();
  const [result, setResult] = useState<ResearchResult | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.research(researchForm as ResearchRequest),
    onSuccess: (data) => {
      setResult(data);
      toast({ title: "研究完成", description: "回测已完成，请查看结果。" });
      queryClient.invalidateQueries({ queryKey: ["research-history"] });
      // Odyssey-UI REV-012: run counters live in the monitoring snapshot;
      // without this they lag up to a full poll interval.
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    },
    onError: (error) => {
      toast({
        title: "研究失败",
        description: error instanceof Error ? error.message : "未知错误",
        variant: "destructive",
      });
    },
  });

  const historyItems = Array.isArray(history) ? history : (history as { items?: unknown[] })?.items ?? [];

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">策略研究</h2>
          <p className="text-sm text-muted-foreground">回测验证策略表现</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Form */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">研究配置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label htmlFor="research-strategy" className="mb-1 block text-xs text-muted-foreground">策略</label>
              <select
              id="research-strategy"
                value={researchForm.strategy}
                onChange={(e) => setResearchForm({ strategy: e.target.value })}
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
                <label htmlFor="research-symbol" className="mb-1 block text-xs text-muted-foreground">交易对</label>
                <Input
              id="research-symbol"
                  value={researchForm.symbol}
                  onChange={(e) => setResearchForm({ symbol: e.target.value })}
                />
              </div>
              <div>
                <label htmlFor="research-capital" className="mb-1 block text-xs text-muted-foreground">初始资金</label>
                <Input
              id="research-capital"
                  type="number"
                  min="1"
                  value={researchForm.capital}
                  onChange={(e) => setResearchForm({ capital: toFiniteNumber(e.target.value) })}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="research-start" className="mb-1 block text-xs text-muted-foreground">开始日期</label>
                <Input
              id="research-start"
                  type="date"
                  value={researchForm.start}
                  onChange={(e) => setResearchForm({ start: e.target.value })}
                />
              </div>
              <div>
                <label htmlFor="research-end" className="mb-1 block text-xs text-muted-foreground">结束日期</label>
                <Input
              id="research-end"
                  type="date"
                  value={researchForm.end}
                  onChange={(e) => setResearchForm({ end: e.target.value })}
                />
              </div>
            </div>

            <div>
              <label htmlFor="research-fee" className="mb-1 block text-xs text-muted-foreground">手续费率</label>
              <Input
              id="research-fee"
                type="number"
                min="0"
                step="0.0001"
                value={researchForm.fee}
                onChange={(e) => setResearchForm({ fee: toFiniteNumber(e.target.value, 0.001) })}
              />
            </div>

            <Button
              className="w-full"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              aria-busy={mutation.isPending}
            >
              <Play className="mr-2 h-4 w-4" />
              {mutation.isPending ? "研究中..." : "启动研究"}
            </Button>

            {mutation.isError && (
              <p className="text-sm text-destructive" role="alert">错误: {mutation.error.message}</p>
            )}
          </CardContent>
        </Card>

        {/* Result */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">研究结果</CardTitle>
          </CardHeader>
          <CardContent>
            {mutation.isPending ? (
              <div className="py-8 text-center text-sm text-muted-foreground">研究中...</div>
            ) : result ? (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <Badge variant="go">{result.strategy}</Badge>
                  <Badge variant="outline">{result.symbol}</Badge>
                </div>

                <div>
                  <SectionHeader title="回测指标" />
                  <div className="grid grid-cols-2 gap-3 rounded-lg bg-muted/30 p-3">
                    {(result.metrics ? Object.entries(result.metrics) : []).map(([key, value]) => (
                      <div key={key}>
                        <p className="text-xs text-muted-foreground">{key}</p>
                        <p className="text-sm font-semibold">
                          {typeof value === "number" ? value.toFixed(4) : String(value)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                {result.report && (
                  <div>
                    <SectionHeader title="报告" />
                    <p className="whitespace-pre-wrap text-xs text-muted-foreground">
                      {result.report}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-muted-foreground">
                配置参数后启动研究
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* History — RC-4 (P2-12): 空状态 = 确认 + 价值 + 行动 */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">研究历史</CardTitle>
            <Button variant="outline" size="sm" onClick={() => refetchHistory()}>
              <RefreshCw className="mr-2 h-3 w-3" />
              刷新
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {historyError ? (
            <ErrorState
              detail={historyErr instanceof Error ? historyErr.message : "加载研究历史失败"}
              onRetry={() => refetchHistory()}
            />
          ) : historyLoading ? (
            <PanelLoading />
          ) : historyItems.length === 0 ? (
            <EmptyState
              title="暂无研究记录"
              description="配置参数并启动第一次回测后，研究的历史记录将显示在这里。建议定期清理过期的研究数据以节省空间。"
            />
          ) : (
            <div className="space-y-2">
              {historyItems.slice(0, 6).map((item: Record<string, unknown>, i: number) => {
                const request = (item.request ?? item.payload ?? {}) as Record<string, unknown>;
                return (
                  <div key={(item.record_id as string) ?? i} className="rounded-lg border p-3">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-xs">
                        {(request.strategy as string) ?? "unknown"}
                      </Badge>
                      <Badge variant="secondary" className="text-xs">
                        {(request.symbol as string) ?? "N/A"}
                      </Badge>
                      {typeof item.created_at === "string" && (
                        <span className="ml-auto text-xs text-muted-foreground">
                          {fmtDateTime(item.created_at)}
                        </span>
                      )}
                    </div>
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
