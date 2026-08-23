import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type SessionStartRequest, type Strategy } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MetricsRow } from "@/components/metric-card";
import { ErrorState } from "@/components/feedback";
import { LiveWarningBanner } from "@/components/LiveWarningBanner";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { LiveModeConfirmDialog } from "@/components/LiveModeConfirmDialog";
import { useToast } from "@/hooks/use-toast";
import { Play, Square, RefreshCw, AlertCircle } from "lucide-react";
import { toFiniteNumber } from "@/lib/form-utils";
import { useStrategiesQuery } from "@/hooks/use-strategies-query";

export function SessionPanel() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  // UI3-H3: destructive stop button needs a confirmation step.
  const [showStopConfirm, setShowStopConfirm] = useState(false);
const { data: strategies } = useStrategiesQuery();

  const { data: snapshot, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["session"],
    queryFn: () => api.sessionSnapshot(),
    // REV-019-RV5: an idle session's payload never changes — poll only
    // while a session is actually running.
    refetchInterval: (query) => (query.state.data?.running ? 5000 : false),
  });

  const [form, setForm] = useState<SessionStartRequest>({
    mode: "paper",
    strategies: ["trend_following"],
    symbol: "BTC/USDT",
    timeframe: "1h",
    interval_seconds: 60,
    capital: 10000,
  });

  const startMutation = useMutation({
    mutationFn: () => api.sessionStart(form),
    onSuccess: () => {
      toast({ title: "会话已启动", description: "交易会话已成功启动。" });
      queryClient.invalidateQueries({ queryKey: ["session"] });
      queryClient.invalidateQueries({ queryKey: ["execution"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    },
    onError: (error) => {
      toast({
        title: "启动失败",
        description: error instanceof Error ? error.message : "未知错误",
        variant: "destructive",
      });
    },
  });

  const stopMutation = useMutation({
    mutationFn: () => api.sessionStop(),
    onSuccess: () => {
      toast({
        title: "会话已停止",
        description: `会话已于 ${new Date().toLocaleTimeString()} 优雅退出。`,
      });
      queryClient.invalidateQueries({ queryKey: ["session"] });
      queryClient.invalidateQueries({ queryKey: ["execution"] });
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    },
    onError: (error) => {
      // P0 H7: 停止失败强反馈——最危险形态，用户以为已停止实际仍在跑
      toast({
        title: "停止失败",
        description: "会话可能仍在运行，请立即检查执行情况面板。",
        variant: "destructive",
      });
      void error; // error detail shown in inline card below
    },
  });

  // P0 H3: 实盘启动需二次确认
  const handleStart = () => {
    if (form.mode === "live") {
      setShowLiveConfirm(true);
    } else {
      startMutation.mutate();
    }
  };

  const handleConfirmLiveStart = () => {
    setShowLiveConfirm(false);
    startMutation.mutate();
  };

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

  const isRunning = snapshot?.running ?? false;
  const portfolio = snapshot?.portfolio ?? { cash: 0, equity: 0, drawdown: 0 };
  const positions = snapshot?.positions ?? [];
  const orders = snapshot?.open_orders ?? [];

  return (
    <div className="@container space-y-6">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">交易会话</h2>
          <p className="text-sm text-muted-foreground">
            {isRunning ? (
              <span className="text-status-go">运行中</span>
            ) : (
              <span className="text-muted-foreground">已停止</span>
            )}
            {snapshot?.session_id && ` · ${snapshot.session_id.slice(0, 8)}...`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            刷新
          </Button>
          {isRunning ? (
            <>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setShowStopConfirm(true)}
                disabled={stopMutation.isPending}
                aria-busy={stopMutation.isPending}
              >
                <Square className="mr-2 h-4 w-4" />
                {stopMutation.isPending ? "停止中..." : "停止"}
              </Button>
              <Dialog open={showStopConfirm} onOpenChange={setShowStopConfirm}>
                <DialogContent className="max-w-sm">
                  <DialogHeader>
                    <DialogTitle>确认停止会话？</DialogTitle>
                    <DialogDescription>
                      将取消所有挂单并断开交易所连接。若当前为实盘会话，停止后需重新校验持仓才能再次启动。
                    </DialogDescription>
                  </DialogHeader>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => setShowStopConfirm(false)}>
                      取消
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => {
                        stopMutation.mutate();
                        setShowStopConfirm(false);
                      }}
                      disabled={stopMutation.isPending}
                    >
                      确认停止
                    </Button>
                  </div>
                </DialogContent>
              </Dialog>
            </>
          ) : (
            <Button
              size="sm"
              onClick={handleStart}
              disabled={startMutation.isPending}
              aria-busy={startMutation.isPending}
            >
              <Play className="mr-2 h-4 w-4" />
              {startMutation.isPending ? "启动中..." : "启动"}
            </Button>
          )}
        </div>
      </div>

      {/* Status Messages */}
      {startMutation.isError && (
        <Card className="border-status-danger/30 bg-status-danger/5">
          <CardContent className="flex items-center gap-3 py-4">
            <AlertCircle className="h-4 w-4 text-status-danger" />
            <p className="text-sm text-status-danger">启动失败：{startMutation.error.message}</p>
          </CardContent>
        </Card>
      )}
      {startMutation.isSuccess && (
        <Card className="border-status-go/30 bg-status-go/5">
          <CardContent className="py-4">
            <p className="text-sm text-status-go">会话已启动</p>
          </CardContent>
        </Card>
      )}
      {/* P0 H7: 停止失败内联错误卡片 */}
      {stopMutation.isError && (
        <Card className="border-status-danger/30 bg-status-danger/5">
          <CardContent className="flex items-center justify-between gap-3 py-4">
            <div className="flex items-center gap-3">
              <AlertCircle className="h-4 w-4 shrink-0 text-status-danger" />
              <div>
                <p className="text-sm font-medium text-status-danger">停止失败：会话可能仍在运行</p>
                <p className="text-xs text-status-danger/80">
                  {stopMutation.error instanceof Error ? stopMutation.error.message : "未知错误"}
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => stopMutation.mutate()}>
              重试停止
            </Button>
          </CardContent>
        </Card>
      )}

      {/* RC-2 (P1-4): 主指标 + 内联统计 */}
      <MetricsRow
        featured={{ label: "权益", value: portfolio.equity.toLocaleString(undefined, { maximumFractionDigits: 2 }), tone: portfolio.equity > 0 ? "go" : "default" }}
        items={[
          { label: "现金", value: portfolio.cash.toLocaleString(undefined, { maximumFractionDigits: 2 }) },
          {
            label: "回撤",
            value: `${(portfolio.drawdown * 100).toFixed(2)}%`,
            tone: portfolio.drawdown > 0.05 ? "danger" : portfolio.drawdown > 0.02 ? "warn" : "default",
          },
          { label: "持仓数", value: positions.length },
        ]}
      />

      {/* Session Config */}
      {!isRunning && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">会话配置</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* P0 H3: 实盘模式持久警告条 */}
            <LiveWarningBanner mode={form.mode} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">模式</label>
                <select
                  value={form.mode}
                  onChange={(e) => setForm({ ...form, mode: e.target.value })}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <option value="paper">模拟盘</option>
                  <option value="live">实盘</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">交易对</label>
                <Input
                  value={form.symbol}
                  onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">时间周期</label>
                <Input
                  value={form.timeframe}
                  onChange={(e) => setForm({ ...form, timeframe: e.target.value })}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-muted-foreground">初始资金</label>
                <Input
                  type="number"
                  min="1"
                  value={form.capital}
                  onChange={(e) => setForm({ ...form, capital: toFiniteNumber(e.target.value) })}
                />
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted-foreground">策略</label>
              <div className="space-y-1">
                {strategies?.map((s: Strategy) => (
                  <label key={s.strategy_id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.strategies.includes(s.strategy_id)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setForm({ ...form, strategies: [...form.strategies, s.strategy_id] });
                        } else {
                          setForm({
                            ...form,
                            strategies: form.strategies.filter((id) => id !== s.strategy_id),
                          });
                        }
                      }}
                      className="rounded border-input"
                    />
                    <span className="text-sm">{s.title}</span>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-1 block text-xs text-muted-foreground">执行间隔 (秒)</label>
              <Input
                type="number"
                min="1"
                value={form.interval_seconds}
                onChange={(e) => setForm({ ...form, interval_seconds: toFiniteNumber(e.target.value, 1) })}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Positions */}
      {positions.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">持仓 ({positions.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {positions.map((pos, i) => (
                <div key={i} className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <Badge variant={pos.side === "long" ? "go" : "danger"} className="text-xs">
                      {pos.side}
                    </Badge>
                    <span className="text-sm font-medium">{pos.symbol}</span>
                  </div>
                  <div className="text-right">
                    <p className="text-sm">
                      {pos.quantity} @ {pos.entry_price.toFixed(2)}
                    </p>
                    <p
                      className={`text-xs ${
                        pos.unrealized_pnl >= 0 ? "text-status-go" : "text-status-danger"
                      }`}
                    >
                      PnL: {pos.unrealized_pnl.toFixed(2)} ({(pos.pnl_pct * 100).toFixed(2)}%)
                    </p>
                  </div>
                </div>
              ))}
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
                      {order.side}
                    </Badge>
                    <span className="text-sm">{order.symbol}</span>
                    <Badge variant="outline" className="text-xs">{order.order_type}</Badge>
                  </div>
                  <div className="text-right">
                    <p className="text-sm">{order.quantity} @ {order.price}</p>
                    <p className="text-xs text-muted-foreground">{order.status}</p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Last Error */}
      {snapshot?.last_error && (
        <Card className="border-status-danger/30 bg-status-danger/5">
          <CardContent className="flex items-center gap-3 py-4">
            <AlertCircle className="h-4 w-4 shrink-0 text-status-danger" />
            <p className="text-sm text-status-danger">{snapshot.last_error}</p>
          </CardContent>
        </Card>
      )}

      {/* P0 H3: 实盘启动确认对话框 */}
      <LiveModeConfirmDialog
        open={showLiveConfirm}
        onConfirm={handleConfirmLiveStart}
        onCancel={() => setShowLiveConfirm(false)}
        isSubmitting={startMutation.isPending}
      />
    </div>
  );
}
