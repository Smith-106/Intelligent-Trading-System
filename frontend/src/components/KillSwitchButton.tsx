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
import { useToast } from "@/hooks/use-toast";
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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const handleSubmit = async () => {
    if (!reason.trim()) return;

    setIsSubmitting(true);
    try {
      await api.sessionKillSwitch(reason.trim());

      toast({
        title: "紧急停止已触发",
        description: "会话已被强制终止，请检查风险评估日志。",
        variant: "destructive",
      });

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["execution"] }),
        queryClient.invalidateQueries({ queryKey: ["session"] }),
        // REV-019-RV1: monitoring carries runtime.active_session / status —
        // stale values here are worst exactly when the operator just killed
        // the session.
        queryClient.invalidateQueries({ queryKey: ["monitoring"] }),
      ]);

      setOpen(false);
      setReason("");
    } catch (error) {
      toast({
        title: "触发失败",
        description: error instanceof Error ? error.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

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
