import { useQuery } from "@tanstack/react-query";
import { api, type MonitoringSnapshot } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricsRow, StatusRow } from "@/components/metric-card";
import { ErrorState } from "@/components/feedback";
import { CollapsibleSection } from "@/components/collapsible-section";
import { AlertTriangle, XCircle, RefreshCw } from "lucide-react";
import { DATA_MODE_LABELS, labelFor } from "@/lib/labels";

function healthToneClass(tone: string): string {
  switch (tone) {
    case "accent":
      return "text-status-go";
    case "warning":
      return "text-status-warn";
    case "danger":
      return "text-status-danger";
    default:
      return "text-muted-foreground";
  }
}

export function MonitoringPanel() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["monitoring"],
    queryFn: () => api.monitoring(),
    refetchInterval: 15000,
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

  return <MonitoringContent data={data} onRefresh={() => refetch()} isRefreshing={isFetching} />;
}

function MonitoringContent({
  data,
  onRefresh,
  isRefreshing,
}: {
  data: MonitoringSnapshot;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const { health, metrics, platform, runtime, services, internal_metrics, alerts } = data;

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">系统监控</h2>
          <p className="text-sm text-muted-foreground">
            <span className={healthToneClass(health.overall_tone)}>{health.overall_label}</span>
            {" · "}
            {health.summary}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* Health Signals */}
      {health.signals.length > 0 && (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="py-4">
            <ul className="space-y-1">
              {health.signals.map((signal, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  {signal}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* RC-2 (P1-4): 主指标 + 内联统计 */}
      <MetricsRow
        featured={{
          label: "服务可用",
          value: `${metrics.services_up}/${metrics.services_total}`,
          tone: metrics.services_up === metrics.services_total ? "go" : "warn",
        }}
        items={[
          {
            label: "验证通过",
            value: metrics.validation_go,
            tone: metrics.validation_go > 0 ? "go" : "default",
          },
          {
            label: "验证拒绝",
            value: metrics.validation_no_go,
            tone: metrics.validation_no_go > 0 ? "danger" : "default",
          },
          {
            label: "告警事件",
            value: metrics.warning_events + metrics.error_events,
            tone:
              metrics.error_events > 0
                ? "danger"
                : metrics.warning_events > 0
                  ? "warn"
                  : "default",
          },
        ]}
      />

      {/* Runtime Status — RC-2: 移除冗余图标标题 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">运行时状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <StatusRow
              label="会话状态"
              value={runtime.status_label}
              tone={runtime.status_tone === "accent" ? "go" : runtime.status_tone === "muted" ? "default" : "warn"}
            />
            <StatusRow
              label="活跃会话"
              value={runtime.active_session ? "是" : "否"}
              tone={runtime.active_session ? "go" : "default"}
            />
            <StatusRow label="持仓数" value={runtime.open_positions} />
            <StatusRow label="挂单数" value={runtime.pending_orders} />
          </div>
        </CardContent>
      </Card>

      {/* Services */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">服务状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {services.map((service) => (
              <div key={service.service_id} className="flex items-center justify-between rounded-lg border p-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{service.label}</span>
                    <Badge
                      variant={
                        service.reachable ? "go" : service.tone === "danger" ? "danger" : "warn"
                      }
                      className="text-xs"
                    >
                      {service.status_label}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{service.status_hint}</p>
                </div>
                {service.port && (
                  <span className="text-xs text-muted-foreground">:{service.port}</span>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Internal Metrics */}
      {internal_metrics.available && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">内部指标</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
              {internal_metrics.portfolio_value !== null && (
                <div>
                  <p className="text-xs text-muted-foreground">组合价值</p>
                  <p className="text-lg font-bold">{internal_metrics.portfolio_value.toLocaleString()}</p>
                </div>
              )}
              {internal_metrics.portfolio_cash !== null && (
                <div>
                  <p className="text-xs text-muted-foreground">现金</p>
                  <p className="text-lg font-bold">{internal_metrics.portfolio_cash.toLocaleString()}</p>
                </div>
              )}
              {internal_metrics.positions_count !== null && (
                <div>
                  <p className="text-xs text-muted-foreground">持仓数</p>
                  <p className="text-lg font-bold">{internal_metrics.positions_count}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-muted-foreground">订单总数</p>
                <p className="text-lg font-bold">{internal_metrics.orders_total}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">信号总数</p>
                <p className="text-lg font-bold">{internal_metrics.signals_generated_total}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">风险事件</p>
                <p className="text-lg font-bold">{internal_metrics.risk_events_total}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Alerts */}
      {alerts.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">告警 ({alerts.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {alerts.map((alert, i) => (
                <div
                  key={i}
                  className={`flex items-start gap-3 rounded-lg border p-3 ${
                    alert.tone === "danger"
                      ? "border-status-danger/30 bg-status-danger/5"
                      : "border-status-warn/30 bg-status-warn/5"
                  }`}
                >
                  {alert.tone === "danger" ? (
                    <XCircle className="h-4 w-4 shrink-0 text-status-danger" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 shrink-0 text-status-warn" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{alert.title}</span>
                      <Badge variant="outline" className="text-xs">
                        {alert.source}
                      </Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{alert.message}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Platform Info — RC-2 (P2-11): 参考性信息默认折叠 */}
      <CollapsibleSection title="平台信息">
        <div className="space-y-1">
          <StatusRow label="版本" value={`v${platform.version}`} />
          <StatusRow label="阶段" value={platform.phase} />
          <StatusRow label="数据模式" value={labelFor(DATA_MODE_LABELS, platform.data_mode)} />
          <StatusRow label="交易对数" value={platform.symbol_count} />
          <StatusRow
            label="Docker"
            value={platform.docker_available ? "可用" : "不可用"}
            tone={platform.docker_available ? "go" : "warn"}
          />
          <StatusRow
            label="Kill Switch"
            value={platform.kill_switch_enabled ? "已启用" : "未启用"}
            tone={platform.kill_switch_enabled ? "go" : "danger"}
          />
        </div>
      </CollapsibleSection>
    </div>
  );
}
