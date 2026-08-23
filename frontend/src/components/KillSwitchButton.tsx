import { useState } from "react";
import { AlertTriangle, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMutationFeedback } from "@/hooks/use-mutation-feedback";
import { api } from "@/lib/api-client";
import { useQueryClient } from "@tanstack/react-query";

/**
 * P0 H2: Kill Switch 紧急停止按钮
 * - 仅在会话运行时可点击
 * - 点击后弹出确认对话框（必填 reason）
 * - 提交后 destructive toast + 立即刷新 execution/session 查询
 */
export function KillSwitchButton({ isRunning }: { isRunning: boolean }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();

  // REV-023-RV2: was toast-only via a hand-rolled try/catch — the most
  // dangerous operation had the least traceable feedback. Now unified:
  // destructive toast (emergency semantics) + inline notice inside the
  // dialog on failure.
  const killFeedback = useMutationFeedback({
    mutationFn: () => api.sessionKillSwitch(reason.trim()),
    onSuccess: {
      title: "紧急停止已触发",
      description: "会话已被强制终止，请检查风险评估日志。",
      variant: "destructive",
    },
    onError: { title: "触发失败", description: (e) => (e instanceof Error ? e.message : "未知错误") },
    onSettledExtra: () => {
      queryClient.invalidateQueries({ queryKey: ["execution"] });
      queryClient.invalidateQueries({ queryKey: ["session"] });
      // REV-019-RV1: monitoring carries runtime.active_session / status —
      // stale values here are worst exactly when the operator just killed
      // the session.
      queryClient.invalidateQueries({ queryKey: ["monitoring"] });
    },
    inlineMs: 0, // 错误保留至用户处理
  });

  const handleSubmit = async () => {
    if (!reason.trim()) return;
    try {
      await killFeedback.mutateAsync(undefined as never);
      setOpen(false);
      setReason("");
    } catch {
      // failure already surfaced via toast + inline notice
    }
  };
  const isSubmitting = killFeedback.mutation.isPending;

  return (
    <>
      <Button
        variant="destructive"
        size="sm"
        onClick={() => setOpen(true)}
        disabled={!isRunning}
        className="gap-2"
        aria-label="触发紧急停止开关"
      >
        <AlertTriangle className="h-4 w-4" />
        {isRunning ? "紧急停止" : "已停止"}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent aria-describedby="kill-switch-description">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <Zap className="h-5 w-5" />
              紧急停止确认
            </DialogTitle>
            <DialogDescription id="kill-switch-description">
              此操作将立即终止当前交易会话并关闭所有未成交订单。请提供终止原因。
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <label htmlFor="kill-reason" className="text-sm font-medium">
                终止原因 *
              </label>
              <Input
                id="kill-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="例如：风控规则触发、异常市场情况等"
                aria-required="true"
              />
            </div>

            {killFeedback.notice?.kind === "error" && (
              <p role="alert" className="text-sm text-status-danger">
                触发失败：{killFeedback.notice.detail}
              </p>
            )}
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              <strong>注意：</strong>此操作会被记录到风控日志，无法撤销。
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={isSubmitting}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={handleSubmit}
              disabled={!reason.trim() || isSubmitting}
            >
              {isSubmitting ? "正在触发..." : "确认触发"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
