import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MetricsRow, StatusRow } from "@/components/metric-card";
import { ErrorState, EmptyState } from "@/components/feedback";
import { CollapsibleSection } from "@/components/collapsible-section";
import { Download, RefreshCw } from "lucide-react";

function dataModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    market: "Market 数据",
    "demo-seeded": "演示数据",
    "source-unknown": "来源未标注",
    hybrid: "混合数据",
    unknown: "未检测",
  };
  return labels[mode] ?? mode;
}

function dataModeTone(mode: string): "go" | "warn" | "danger" | "default" {
  if (mode === "market") return "go";
  if (mode === "demo-seeded") return "warn";
  if (mode === "hybrid") return "warn";
  if (mode === "source-unknown") return "danger";
  return "default";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function DataPanel() {
  const queryClient = useQueryClient();
  const { data: snapshot, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["data-snapshot"],
    queryFn: () => api.dataSnapshot(),
    refetchInterval: 60000,
  });

  const [downloadSymbol, setDownloadSymbol] = useState("BTC/USDT");
  const [downloadTimeframe, setDownloadTimeframe] = useState("1h");
  const [downloadStart, setDownloadStart] = useState("2024-01-01");
  const [downloadEnd, setDownloadEnd] = useState("");
  const downloadMutation = useMutation({
    mutationFn: () => {
      const endDate: string = downloadEnd.trim() !== "" ? downloadEnd.trim() : new Date().toISOString().slice(0, 10);
      return api.dataDownload({
        symbol: downloadSymbol,
        timeframe: downloadTimeframe,
        start: downloadStart,
        end: endDate,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["data-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
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
              <label className="mb-1 block text-xs text-muted-foreground">交易对</label>
              <Input
                value={downloadSymbol}
                onChange={(e) => setDownloadSymbol(e.target.value)}
                placeholder="BTC/USDT"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">时间周期</label>
              <Input
                value={downloadTimeframe}
                onChange={(e) => setDownloadTimeframe(e.target.value)}
                placeholder="1h"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">开始日期</label>
              <Input
                type="date"
                value={downloadStart}
                onChange={(e) => setDownloadStart(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">结束日期</label>
              <Input
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
        {downloadMutation.isError && (
          <p className="mt-2 text-sm text-destructive">下载失败：{downloadMutation.error.message}</p>
        )}
          {downloadMutation.isSuccess && (
            <p className="mt-2 text-sm text-status-go">
              下载完成: {downloadMutation.data.rows_saved} 行数据
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
                    <th className="pb-2 pr-4">交易对</th>
                    <th className="pb-2 pr-4">来源</th>
                    <th className="hidden pb-2 pr-4 sm:table-cell">文件数</th>
                    <th className="hidden pb-2 pr-4 sm:table-cell">起始日期</th>
                    <th className="hidden pb-2 pr-4 sm:table-cell">结束日期</th>
                    <th className="pb-2 pr-4">覆盖天数</th>
                    <th className="pb-2">数据新鲜度</th>
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
                      <td className="hidden py-2 pr-4 sm:table-cell">{formatDate(sym.range_start)}</td>
                      <td className="hidden py-2 pr-4 sm:table-cell">{formatDate(sym.range_end)}</td>
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
                  截至 {formatDate(leaders.latest_symbol.range_end)}
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
