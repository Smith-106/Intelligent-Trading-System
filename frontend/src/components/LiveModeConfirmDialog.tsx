import { useState } from "react";
import { ShieldCheck } from "lucide-react";
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

interface LiveModeConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  isSubmitting: boolean;
}

/**
 * P0 H3: 实盘启动确认对话框
 * 两种方式之一即可启用确认按钮：
 * 1. 勾选"我了解风险"
 * 2. 输入确认词"START LIVE"
 */
export function LiveModeConfirmDialog({
  open,
  onConfirm,
  onCancel,
  isSubmitting,
}: LiveModeConfirmDialogProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  // REV-022-RV10: was `||` — ticking the box OR typing the passphrase alone
        // unlocked live trading. High-risk confirmations require both factors.
        const isConfirmed = acknowledged && confirmText.toUpperCase() === "START LIVE";

  const handleClose = () => {
    setAcknowledged(false);
    setConfirmText("");
    onCancel();
  };

  const handleConfirm = () => {
    setAcknowledged(false);
    setConfirmText("");
    onConfirm();
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) handleClose(); }}>
      <DialogContent aria-describedby="live-confirm-description">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-destructive">
            <ShieldCheck className="h-5 w-5" />
            实盘启动最终确认
          </DialogTitle>
          <DialogDescription id="live-confirm-description">
            再次确认您已阅读所有风险提示，并准备使用真实资金启动交易会话。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="space-y-3">
            <label className="flex cursor-pointer items-center space-x-2">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                id="risk-ack"
                className="h-4 w-4 rounded border-input accent-destructive"
              />
              <span className="text-sm">
                我了解实盘交易存在本金损失风险，已做好充分准备
              </span>
            </label>

            <div>
              <label htmlFor="live-confirm-text" className="text-sm font-medium">
                或输入确认词以继续：
              </label>
              <Input
                id="live-confirm-text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder="START LIVE"
                className="mt-1"
              />
            </div>
          </div>

          <div className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
            <strong>提示：</strong>此为不可逆操作。启动后将实时监控交易事件和风险指标。
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isSubmitting}>
            取消
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={!isConfirmed || isSubmitting}
            aria-disabled={!isConfirmed}
          >
            {isSubmitting ? "正在启动..." : "确认启动实盘"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
