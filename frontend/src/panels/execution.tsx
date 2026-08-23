import {  } from "@tanstack/react-query";
import { PanelError, PanelLoading, usePanelQuery } from "@/hooks/use-panel-query";
import { api, type ExecutionSnapshot } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricsRow, StatusRow } from "@/components/metric-card";
import { CollapsibleSection } from "@/components/collapsible-section";
import { EquityChart } from "@/components/charts/equity-chart";
import { DrawdownChart } from "@/components/charts/drawdown-chart";
import { KillSwitchButton } from "@/components/KillSwitchButton";
import { RefreshCw } from "lucide-react";
import { CopyableText } from "@/components/copyable-text";
import { fmtDateTime, fmtPct } from "@/lib/format";
import { LEVEL_LABELS, MODE_LABELS, ORDER_STATUS_LABELS, ORDER_TYPE_LABELS, SIDE_LABELS, labelFor } from "@/lib/labels";

function toneClass(tone: string): string {
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

export function ExecutionPanel() {
  const { data, isLoading, error, refetch, isFetching } = usePanelQuery(
    ["execution"],
    () => api.execution(),
    10000,
  );

  if (isLoading) return <PanelLoading />;

  if (error) {
    return <PanelError context="执行情况" error={error} onRetry={() => refetch()} />;
  }

  if (!data) return null;

  return <ExecutionContent data={data} onRefresh={() => refetch()} isRefreshing={isFetching} />;
}

function ExecutionContent({
  data,
  onRefresh,
  isRefreshing,
}: {
  data: ExecutionSnapshot;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  const { status, summary, control, risk, positions, orders, events, telemetry } = data;

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">执行引擎</h2>
          <p className="text-sm text-muted-foreground">
            <span className={toneClass(status.tone)}>{status.label}</span>
            {" · "}
            {status.summary}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* RC-2 (P1-4): 主指标 + 内联统计 */}
      <MetricsRow
        featured={{
          label: "权益",
          value: summary.equity.toLocaleString(undefined, { maximumFractionDigits: 2 }),
          // REV-022-RV1: follow PnL sign — equity alone carries no health
          // information (any funded account is > 0).
                      // REV-025-H4: align with the items-row convention (0 = flat = green).
            tone: summary.unrealized_pnl >= 0 ? "go" : "danger",
          hint: `${labelFor(MODE_LABELS, summary.mode)} · ${summary.symbol}`,
        }}
        items={[
          {
            label: "未实现盈亏",
            value: summary.unrealized_pnl.toLocaleString(undefined, { maximumFractionDigits: 2 }),
            tone: summary.unrealized_pnl >= 0 ? "go" : "danger",
          },
          { label: "持仓", value: summary.position_count },
          { label: "挂单", value: summary.order_count },
        ]}
      />

      {/* Status — RC-2: 移除冗余图标标题 */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">执行状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <StatusRow
              label="会话状态"
              value={status.session_label}
              tone={status.session_tone === "accent" ? "go" : status.session_tone === "muted" ? "default" : "warn"}
            />
            <StatusRow label="模式" value={labelFor(MODE_LABELS, summary.mode)} />
            <StatusRow label="交易对" value={summary.symbol} />
            <StatusRow label="时间周期" value={summary.timeframe} />
            <StatusRow label="策略" value={summary.strategy_text} />
            <StatusRow label="运行时间" value={control.uptime_label} />
          </div>
        </CardContent>
      </Card>

      {/* Risk — RC-2: 移除冗余图标标题 + P0 H2 Kill Switch */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base">风险状态</CardTitle>
          <KillSwitchButton isRunning={control.running} />
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            <StatusRow
              label="Kill Switch"
              value={risk.kill_switch_active ? "已激活" : "未激活"}
              tone={risk.kill_switch_active ? "danger" : "go"}
            />
            {risk.kill_switch_reason && (
              <StatusRow label="原因" value={risk.kill_switch_reason} tone="danger" />
            )}
            <StatusRow
              label="回撤状态"
              value={risk.drawdown_ok ? "正常" : "超限"}
              tone={risk.drawdown_ok ? "go" : "danger"}
            />
            <StatusRow label="警告事件" value={risk.warning_events} tone={risk.warning_events > 0 ? "warn" : "default"} />
            <StatusRow label="错误事件" value={risk.error_events} tone={risk.error_events > 0 ? "danger" : "default"} />
          </div>
        </CardContent>
      </Card>

      {/* Portfolio Summary */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">组合概览</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            <div>
              <p className="text-xs text-muted-foreground">现金</p>
              <p className="text-lg font-bold">{summary.cash.toLocaleString(undefined, { maximumFractionDigits: 2 })}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">名义价值</p>
              <p className="text-lg font-bold">{summary.gross_notional.toLocaleString(undefined, { maximumFractionDigits: 2 })}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">待处理名义</p>
              <p className="text-lg font-bold">{summary.pending_notional.toLocaleString(undefined, { maximumFractionDigits: 2 })}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">回撤</p>
              {/* REV-025-H1: drawdown is <=0 from the backend; `> 0` never
                  fired and the raw value printed an odd negative percent. */}
              <p className={`text-lg font-bold ${Math.abs(summary.drawdown) > 0.02 ? "text-status-danger" : ""}`}>
                {fmtPct(Math.abs(summary.drawdown))}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">暴露度</p>
              <p className="text-lg font-bold">{summary.exposure_pct.toFixed(1)}%</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Charts */}
      <div className="grid grid-cols-1 gap-6 @2xl:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">权益曲线</CardTitle>
          </CardHeader>
          <CardContent>
            <EquityChart telemetry={telemetry} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">回撤曲线</CardTitle>
          </CardHeader>
          <CardContent>
            <DrawdownChart telemetry={telemetry} />
          </CardContent>
        </Card>
      </div>

      {/* Positions */}
      {positions.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">持仓 ({positions.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="pb-2 pr-4">交易对</th>
                    <th scope="col" className="pb-2 pr-4">方向</th>
                    <th scope="col" className="pb-2 pr-4">数量</th>
                    <th scope="col" className="pb-2 pr-4">入场价</th>
                    <th scope="col" className="pb-2 pr-4">当前价</th>
                    <th scope="col" className="pb-2 pr-4">盈亏</th>
                    <th scope="col" className="pb-2">收益率</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos) => (
                    <tr key={pos.symbol} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-medium">{pos.symbol}</td>
                      <td className="py-2 pr-4">
                        <Badge variant={pos.side === "long" ? "go" : "danger"} className="text-xs">
                          {labelFor(SIDE_LABELS, pos.side)}
                        </Badge>
                      </td>
                      <td className="py-2 pr-4">{pos.quantity}</td>
                      <td className="py-2 pr-4">{pos.entry_price.toFixed(2)}</td>
                      <td className="py-2 pr-4">{pos.current_price.toFixed(2)}</td>
                      <td className={`py-2 pr-4 ${pos.unrealized_pnl >= 0 ? "text-status-go" : "text-status-danger"}`}>
                        {pos.unrealized_pnl.toFixed(2)}
                      </td>
                      <td className={`py-2 ${pos.pnl_pct >= 0 ? "text-status-go" : "text-status-danger"}`}>
                        {(pos.pnl_pct * 100).toFixed(2)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Orders */}
      {orders.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">挂单 ({orders.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {orders.map((order) => (
                <div key={order.order_id} className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <Badge variant={order.side === "buy" ? "go" : "danger"} className="text-xs">
                      {labelFor(SIDE_LABELS, order.side)}
                    </Badge>
                    <CopyableText value={order.order_id} className="min-w-0 max-w-[140px] text-muted-foreground" />
                    <span className="text-sm">{order.symbol}</span>
                    <Badge variant="outline" className="text-xs">{labelFor(ORDER_TYPE_LABELS, order.order_type)}</Badge>
                  </div>
                  <div className="text-right">
                    <p className="text-sm">{order.quantity} @ {order.price}</p>
                    <p className="text-xs text-muted-foreground">{labelFor(ORDER_STATUS_LABELS, order.status)}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Events — RC-2 (P2-11): 日志型数据默认折叠 */}
      {events.length > 0 && (
        <CollapsibleSection title={`执行事件 (${events.length})`}>
          <div className="space-y-1">
            {events.map((event, i) => (
              <div
                key={i}
                className={`rounded-lg border p-3 ${
                  event.level === "error" || event.level === "critical"
                    ? "border-status-danger/30 bg-status-danger/5"
                    : event.level === "warning"
                      ? "border-status-warn/30 bg-status-warn/5"
                      : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      event.level === "error" || event.level === "critical"
                        ? "danger"
                        : event.level === "warning"
                          ? "warn"
                          : "secondary"
                    }
                    className="text-xs"
                  >
                    {labelFor(LEVEL_LABELS, event.level)}
                  </Badge>
                  <Badge variant="outline" className="text-xs">{event.event_type}</Badge>
                  <span className="text-sm">{event.title}</span>
                  {typeof event.created_at === "string" && (
                    <span className="ml-auto text-xs text-muted-foreground">
                      {fmtDateTime(event.created_at)}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{event.message}</p>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}
    </div>
  );
}
