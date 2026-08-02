import { useQuery } from "@tanstack/react-query";
import { api, type OverviewData } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricsRow, StatusRow, SectionHeader } from "@/components/metric-card";
import { ErrorState, EmptyState } from "@/components/feedback";
import { useUIStore } from "@/stores/ui-store";
import { TrendingUp, Server, RefreshCw, ExternalLink } from "lucide-react";

function dataModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    live: "实时数据",
    parquet: "本地数据",
    mixed: "混合模式",
    unknown: "未检测",
  };
  return labels[mode] ?? mode;
}

function dataModeTone(mode: string): "go" | "warn" | "default" {
  if (mode === "live") return "go";
  if (mode === "parquet") return "default";
  return "warn";
}

export function OverviewPanel() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["overview"],
    queryFn: () => api.overview(),
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-muted-foreground">加载中...</div>
      </div>
    );
  }

  if (error) {
    // RC-4 (P1-3): what + why + fix 错误指引
    return <ErrorState detail={error.message} onRetry={() => refetch()} />;
  }

  if (!data) return null;

  return <OverviewContent data={data} onRefresh={() => refetch()} isRefreshing={isFetching} />;
}

function OverviewContent({
  data,
  onRefresh,
  isRefreshing,
}: {
  data: OverviewData;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const dataMode = data.data.mode;
  const sourceCounts = data.data.source_counts;
  const setActivePanel = useUIStore((s) => s.setActivePanel);

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 clamp 20→24px */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">系统总览</h2>
          <p className="text-sm text-muted-foreground">
            Phase {data.phase} · v{data.version}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* RC-2 (P1-4): 主指标 + 内联统计，替代 5 个等大 MetricCard */}
      <MetricsRow
        featured={{
          label: "策略数",
          value: data.strategies.count,
          tone: data.strategies.count > 0 ? "go" : "default",
        }}
        items={[
          {
            label: "数据交易对",
            value: data.data.symbol_count,
            tone: data.data.symbol_count > 0 ? "go" : "default",
          },
          { label: "数据模式", value: dataModeLabel(dataMode), tone: dataModeTone(dataMode) },
          { label: "Prometheus", value: data.monitoring.prometheus_port },
          { label: "Grafana", value: data.monitoring.grafana_port },
        ]}
      />

      {/* Data Sources — RC-2: 移除冗余图标标题 */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">数据来源</CardTitle>
            <Badge variant={dataModeTone(dataMode) === "go" ? "go" : "secondary"}>
              {dataModeLabel(dataMode)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            {Object.entries(sourceCounts).map(([source, count]) => (
              <StatusRow key={source} label={source} value={`${count} 个交易对`} tone="default" />
            ))}
            {Object.keys(sourceCounts).length === 0 && (
              // RC-4 (P2-12): 空状态 = 确认 + 价值 + 行动
              <EmptyState
                title="暂无数据来源"
                description="还没有任何行情数据入库。下载数据后，各来源的交易对统计将显示在这里。"
                action={
                  <Button variant="outline" size="sm" onClick={() => setActivePanel("data")}>
                    前往数据中心
                  </Button>
                }
              />
            )}
          </div>
        </CardContent>
      </Card>

      {/* RC-2 (P2-14): 风控 + 执行配置合并为单卡片双栏，减少卡片重复 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">风控与执行配置</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
            <div>
              <SectionHeader title="风控" />
              <div className="space-y-1">
                <StatusRow
                  label="最大回撤"
                  value={`${(data.risk.max_drawdown * 100).toFixed(1)}%`}
                  tone={data.risk.max_drawdown < 0.1 ? "go" : "warn"}
                />
                <StatusRow
                  label="日损失限制"
                  value={`${(data.risk.daily_loss_limit * 100).toFixed(1)}%`}
                />
                <StatusRow
                  label="周损失限制"
                  value={`${(data.risk.weekly_loss_limit * 100).toFixed(1)}%`}
                />
                <StatusRow
                  label="Kill Switch"
                  value={data.risk.kill_switch_enabled ? "已启用" : "未启用"}
                  tone={data.risk.kill_switch_enabled ? "go" : "danger"}
                />
              </div>
            </div>
            <div>
              <SectionHeader title="执行" />
              <div className="space-y-1">
                <StatusRow label="交易模式" value={data.execution.mode} />
                <StatusRow label="滑点" value={`${(data.execution.slippage * 100).toFixed(2)}%`} />
                <StatusRow label="Maker 费率" value={`${(data.execution.maker_fee * 100).toFixed(3)}%`} />
                <StatusRow label="Taker 费率" value={`${(data.execution.taker_fee * 100).toFixed(3)}%`} />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Monitoring Links */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">监控服务</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <a
              href={data.monitoring.prometheus_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-accent/10"
            >
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-primary" />
                <span className="text-base">Prometheus</span>
              </div>
              <ExternalLink className="h-3 w-3 text-muted-foreground" />
            </a>
            <a
              href={data.monitoring.grafana_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-accent/10"
            >
              <div className="flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-primary" />
                <span className="text-base">Grafana</span>
              </div>
              <ExternalLink className="h-3 w-3 text-muted-foreground" />
            </a>
          </div>
          {data.docker_available && (
            <p className="mt-3 text-xs text-status-go">Docker 可用</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
