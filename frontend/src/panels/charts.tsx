/**
 * ChartsPanel — multi-timeframe candlestick view (UI-REV016).
 *
 * Data flow: POST /api/analysis/multi-tf (fields=full) → pick the selected
 * timeframe's candles → CandleChart (lightweight-charts v4). The selected
 * symbol/timeframe/volume toggle persist in workbench-store so the panel
 * survives the key-based remount on tab switch.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, RefreshCw } from "lucide-react";

import { api } from "@/lib/api-client";
import { ErrorState, EmptyState } from "@/components/feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { CandleChart } from "@/components/charts/candle-chart";
import { useWorkbenchStore } from "@/stores/workbench-store";
import type { MultiTfTimeframeResult } from "@/lib/api-client";

/** Quick-access segments + grouped long tail (mirrors backend vocabulary). */
const QUICK_TFS = ["5m", "15m", "1h", "4h", "6h"] as const;
const INTRADAY_TAIL = ["10m", "30m", "45m", "2h", "3h", "5h", "7h", "8h", "12h", "16h"] as const;
const DAILY_TAIL = ["24h", "32h", "2d", "3d", "5d", "7d", "10d", "15d", "30d"] as const;
const ALL_TFS: string[] = [...QUICK_TFS, ...INTRADAY_TAIL, ...DAILY_TAIL];

function TfButton({
  tf,
  active,
  onSelect,
}: {
  tf: string;
  active: boolean;
  onSelect: (tf: string) => void;
}) {
  const handleClick = () => {
    onSelect(tf);
    // REV-017-RV8: auto-collapse the enclosing "更多" dropdown on pick.
    document.activeElement?.closest("details")?.removeAttribute("open");
  };
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={handleClick}
      className={`min-w-9 rounded-md px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
    >
      {tf}
    </button>
  );
}

export function ChartsPanel() {
  const { chartView, setChartView } = useWorkbenchStore();
  const { data: snapshot } = useQuery({
    queryKey: ["data-snapshot"],
    queryFn: () => api.dataSnapshot(),
    staleTime: 60_000,
  });
  const knownSymbols: string[] = useMemo(
    () => (snapshot?.symbols ?? []).map((s) => s.symbol),
    [snapshot],
  );

  const request = useMemo(
    () => ({
      symbols: [chartView.symbol],
      timeframes: ALL_TFS,
      fields: "full" as const,
    }),
    [chartView.symbol],
  );

  // K-line history is not polled; refresh is manual (topbar / Alt+R via
  // PANEL_QUERY_KEYS.charts) or on request change.
  const { data, isLoading, isError, error, refetch, isFetching, isPlaceholderData } =
    useQuery({
    queryKey: ["multi-tf", chartView.symbol, ALL_TFS.join(",")],
    queryFn: ({ signal }) => api.analyzeMultiTf(request, signal),
    enabled: chartView.symbol.trim() !== "",
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });

  const result = data?.results.find((r) => r.symbol === chartView.symbol);
  // REV-017-RV3: while a new symbol's query is in flight, TanStack keeps the
  // previous payload as placeholderData — find() would miss and render a
  // misleading "no data" empty state. The empty branch gates on
  // isPlaceholderData (destructured from useQuery above).
  const tfResult: MultiTfTimeframeResult | undefined = result?.timeframes.find(
    (t) => t.timeframe === chartView.timeframe,
  );
  const candles = tfResult?.candles ?? [];
  const unknownSymbol =
    knownSymbols.length > 0 && !knownSymbols.includes(chartView.symbol);

  return (
    <div className="@container space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">行情图表</h2>
          <p className="text-sm text-muted-foreground">
            多时间框架蜡烛图（5m — 30d 本地重采样）
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative mb-4 sm:mb-1">
              <input
                list="known-symbols"
                value={chartView.symbol}
                onChange={(e) => setChartView({ symbol: e.target.value.toUpperCase() })}
                placeholder="BTC/USDT"
                aria-label="交易对"
                className="flex h-8 w-40 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <datalist id="known-symbols">
                {knownSymbols.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
              {unknownSymbol && (
                <span className="absolute -bottom-4 left-0 text-[10px] text-warning">
                  本地无此交易对缓存
                </span>
              )}
            </div>

            <div
              className="flex items-center gap-0.5 rounded-lg border p-0.5"
              role="group"
              aria-label="时间框架"
            >
              {QUICK_TFS.map((tf) => (
                <TfButton
                  key={tf}
                  tf={tf}
                  active={chartView.timeframe === tf}
                  onSelect={(t) => setChartView({ timeframe: t })}
                />
              ))}
              <details className="relative">
                <summary className="cursor-pointer list-none rounded-md px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
                  更多 ▾
                </summary>
                <div className="absolute right-0 z-20 mt-1 w-max min(420px, calc(100vw - 2rem)) rounded-lg border bg-popover p-3 shadow-lg">
                  <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                    日内（5m 基网格）
                  </p>
                  <div className="mb-2 flex flex-wrap gap-0.5">
                    {INTRADAY_TAIL.map((tf) => (
                      <TfButton
                        key={tf}
                        tf={tf}
                        active={chartView.timeframe === tf}
                        onSelect={(t) => setChartView({ timeframe: t })}
                      />
                    ))}
                  </div>
                  <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                    多日（1d 基网格）
                  </p>
                  <div className="flex flex-wrap gap-0.5">
                    {DAILY_TAIL.map((tf) => (
                      <TfButton
                        key={tf}
                        tf={tf}
                        active={chartView.timeframe === tf}
                        onSelect={(t) => setChartView({ timeframe: t })}
                      />
                    ))}
                  </div>
                </div>
              </details>
            </div>

            <Button
              variant={chartView.showVolume ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={chartView.showVolume}
              onClick={() => setChartView({ showVolume: !chartView.showVolume })}
              title="成交量副图"
            >
              <BarChart3 className="mr-1 h-4 w-4" />
              Vol
            </Button>

            <div className="ml-auto text-xs tabular-nums text-muted-foreground">
              {result ? `${chartView.timeframe} · ${candles.length} bars` : ""}
            </div>
          </div>
        </CardHeader>

        <CardContent>
          <div className="relative h-[480px] min-h-[320px] w-full overflow-hidden rounded-md border">
            {isError ? (
              <div className="p-6">
                <ErrorState
                  detail={error instanceof Error ? error.message : "加载图表失败"}
                  onRetry={() => refetch()}
                />
              </div>
            ) : isLoading ? (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                加载中...
              </div>
            ) : !isPlaceholderData && (candles.length === 0 || tfResult?.insufficient_data) ? (
              <div className="p-6">
                <EmptyState
                  title={`暂无 ${chartView.symbol} ${chartView.timeframe} 数据`}
                  description="该交易对或周期尚未下载。请前往数据中心下载基础数据后返回查看。"
                />
              </div>
            ) : (
              <CandleChart candles={candles} showVolume={chartView.showVolume} />
            )}
            {isFetching && !isLoading && (
              <div className="pointer-events-none absolute inset-0 flex items-start justify-end p-2 transition-opacity duration-150">
                <span className="rounded bg-background/70 px-2 py-0.5 text-xs text-muted-foreground">
                  更新中...
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
