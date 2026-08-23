import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useMutationFeedback } from "@/hooks/use-mutation-feedback";
import { PanelError, PanelLoading, usePanelQuery } from "@/hooks/use-panel-query";
import { api } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MetricsRow, StatusRow } from "@/components/metric-card";
import { EmptyState } from "@/components/feedback";
import { CollapsibleSection } from "@/components/collapsible-section";
import { Download, RefreshCw } from "lucide-react";
import { fmtDate } from "@/lib/format";
import { DATA_MODE_LABELS, labelFor } from "@/lib/labels";

function dataModeLabel(mode: string): string {
  // REV-022-RV4: unified vocabulary (was "Market 数据" style local list).
  return labelFor(DATA_MODE_LABELS, mode);
}

function dataModeTone(mode: string): "go" | "warn" | "danger" | "default" {
  if (mode === "market") return "go";
  if (mode === "demo-seeded") return "warn";
  if (mode === "hybrid") return "warn";
  if (mode === "source-unknown") return "danger";
  return "default";
}


export function DataPanel() {
  const queryClient = useQueryClient();
  const { data: snapshot, isLoading, error, refetch, isFetching } = usePanelQuery(
    ["data-snapshot"],
    () => api.dataSnapshot(),
    60000,
  );

  const [downloadSymbol, setDownloadSymbol] = useState("BTC/USDT");
  const [downloadTimeframe, setDownloadTimeframe] = useState("1h");
  const [downloadStart, setDownloadStart] = useState("2024-01-01");
  const [downloadEnd, setDownloadEnd] = useState("");
  // REV-023-RV2: was inline-only — no toast, and the success note stayed
  // forever after editing the form. Unified hook adds the toast and
  // auto-clears the notice (errors persist until dismissed/next attempt).
  const downloadFeedback = useMutationFeedback({
    mutationFn: () => {
      const endDate: string = downloadEnd.trim() !== "" ? downloadEnd.trim() : new Date().toISOString().slice(0, 10);
      return api.dataDownload({
        symbol: downloadSymbol,
        timeframe: downloadTimeframe,
        start: downloadStart,
        end: endDate,
      });
    },
        // REV-025-M6: success detail comes from the mutation result now —
    // previously the hook notice carried an empty string and the panel
    // bypassed it to render rows_saved itself.
    onSuccess: { title: "下载完成", description: (d) => `已保存 ${d.rows_saved} 行数据` },
    onError: { title: "下载失败", description: (e) => (e instanceof Error ? e.message : "未知错误") },
    onSettledExtra: () => {
      queryClient.invalidateQueries({ queryKey: ["data-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
      // REV-019-RV2: monitoring's platform block derives from the same scan.
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    },
  });
  const downloadMutation = downloadFeedback.mutation;
  if (isLoading) return <PanelLoading />;

  if (error) {
    return <PanelError context="数据中心" error={error} onRetry={() => refetch()} />;
  }

  if (!snapshot) return null;

  const { summary, storage, leaders, highlights, symbols } = snapshot;

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">数据中心</h2>
          <p className="text-sm text-muted-foreground">
            {dataModeLabel(snapshot.mode)} · {summary.symbol_count} 个交易对
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* Highlights */}
      {highlights.length > 0 && (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="py-4">
            <ul className="space-y-1">
              {highlights.map((text, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  {text}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* RC-2 (P1-4): 主指标 + 内联统计 */}
      <MetricsRow
        featured={{ label: "交易对", value: summary.symbol_count, tone: summary.symbol_count > 0 ? "go" : "default" }}
        items={[
          { label: "Parquet 文件", value: summary.files_total },
          { label: "数据模式", value: dataModeLabel(snapshot.mode), tone: dataModeTone(snapshot.mode) },
          { label: "DuckDB", value: summary.duckdb_exists ? "已就绪" : "未创建", tone: summary.duckdb_exists ? "go" : "default" },
        ]}
      />

      {/* Download Form */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">下载数据</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div>
              <label htmlFor="dl-symbol" className="mb-1 block text-xs text-muted-foreground">交易对</label>
              <Input
                id="dl-symbol"
                value={downloadSymbol}
                onChange={(e) => setDownloadSymbol(e.target.value)}
                placeholder="BTC/USDT"
              />
            </div>
            <div>
              <label htmlFor="dl-timeframe" className="mb-1 block text-xs text-muted-foreground">时间周期</label>
              <Input
                id="dl-timeframe"
                value={downloadTimeframe}
                onChange={(e) => setDownloadTimeframe(e.target.value)}
                placeholder="1h"
              />
            </div>
            <div>
              <label htmlFor="dl-start" className="mb-1 block text-xs text-muted-foreground">开始日期</label>
              <Input
                id="dl-start"
                type="date"
                value={downloadStart}
                onChange={(e) => setDownloadStart(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="dl-end" className="mb-1 block text-xs text-muted-foreground">结束日期</label>
              <Input
                id="dl-end"
                type="date"
                value={downloadEnd}
                onChange={(e) => setDownloadEnd(e.target.value)}
              />
            </div>
          </div>
          <Button
            className="mt-4"
            onClick={() => downloadMutation.mutate()}
            disabled={downloadMutation.isPending}
          >
            <Download className="mr-2 h-4 w-4" />
            {downloadMutation.isPending ? "下载中..." : "开始下载"}
          </Button>
        {downloadFeedback.notice?.kind === "error" && (
          <p role="alert" className="mt-2 text-sm text-destructive">下载失败：{downloadFeedback.notice.detail}</p>
        )}
          {downloadFeedback.notice?.kind === "success" && (
            <p role="status" className="mt-2 text-sm text-status-go">
              {downloadFeedback.notice.detail}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Symbols Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">交易对覆盖明细</CardTitle>
        </CardHeader>
        <CardContent>
          {symbols.length === 0 ? (
            // RC-4 (P2-12): 空状态 = 确认 + 价值 + 行动
            <EmptyState
              title="暂无交易对数据"
              description="使用上方表单下载第一个交易对的历史行情数据。数据入库后，此处的统计将显示各来源的交易对分布和新鲜度。"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th scope="col" className="pb-2 pr-4">交易对</th>
                    <th scope="col" className="pb-2 pr-4">来源</th>
                    <th scope="col" className="hidden pb-2 pr-4 sm:table-cell">文件数</th>
                    <th scope="col" className="hidden pb-2 pr-4 sm:table-cell">起始日期</th>
                    <th scope="col" className="hidden pb-2 pr-4 sm:table-cell">结束日期</th>
                    <th scope="col" className="pb-2 pr-4">覆盖天数</th>
                    <th scope="col" className="pb-2">数据新鲜度</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.map((sym) => (
                    <tr key={sym.symbol} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-medium">{sym.symbol}</td>
                      <td className="py-2 pr-4">
                        <Badge
                          variant={
                            sym.data_source === "okx"
                              ? "go"
                              : sym.data_source === "demo"
                                ? "warn"
                                : "secondary"
                          }
                          className="text-xs"
                        >
                          {sym.data_source}
                        </Badge>
                      </td>
                      <td className="hidden py-2 pr-4 sm:table-cell">{sym.files}</td>
                      <td className="hidden py-2 pr-4 sm:table-cell">{fmtDate(sym.range_start)}</td>
                      <td className="hidden py-2 pr-4 sm:table-cell">{fmtDate(sym.range_end)}</td>
                      <td className="py-2 pr-4">{sym.coverage_days ?? "—"}</td>
                      <td className="py-2">
                        {sym.last_bar_age_days !== null ? (
                          <span
                            className={
                              sym.last_bar_age_days < 7
                                ? "text-status-go"
                                : sym.last_bar_age_days < 30
                                  ? "text-status-warn"
                                  : "text-status-danger"
                            }
                          >
                            {sym.last_bar_age_days} 天前
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Storage Info — RC-2 (P2-11): 技术路径默认折叠 */}
      <CollapsibleSection title="存储信息">
        <div className="space-y-1">
          <StatusRow label="Parquet 目录" value={storage.parquet_dir} />
          <StatusRow label="DuckDB 路径" value={storage.duckdb_path} />
          <StatusRow
            label="Parquet 目录"
            value={summary.parquet_root_exists ? "存在" : "不存在"}
            tone={summary.parquet_root_exists ? "go" : "danger"}
          />
          <StatusRow label="执行模式" value={storage.execution_mode} />
        </div>
      </CollapsibleSection>

      {/* Leaders */}
      {(leaders.latest_symbol || leaders.widest_symbol) && (
        <div className="grid grid-cols-1 gap-4 @2xl:grid-cols-2">
          {leaders.latest_symbol && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">最新数据</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-lg font-bold">{leaders.latest_symbol.symbol}</p>
                <p className="text-xs text-muted-foreground">
                  截至 {fmtDate(leaders.latest_symbol.range_end)}
                </p>
              </CardContent>
            </Card>
          )}
          {leaders.widest_symbol && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">最宽覆盖</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-lg font-bold">{leaders.widest_symbol.symbol}</p>
                <p className="text-xs text-muted-foreground">
                  {leaders.widest_symbol.files} 个文件 · {leaders.widest_symbol.coverage_days ?? "—"} 天
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
