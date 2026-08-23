/**
 * Copyable text with inline "已复制" feedback (REV-023).
 *
 * Session ids, order ids and storage paths were display-only — operators
 * debugging a support issue had to hand-copy truncated values. Click (or
 * Enter/Space, it's a button) copies the FULL value; the label flips to
 * "已复制" for 2s so the action is confirmed without a toast.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Check, Copy } from "lucide-react";

interface CopyableTextProps {
  /** Full value placed on the clipboard. */
  value: string;
  /** Display form; defaults to `value` (use for truncated previews). */
  display?: string;
  className?: string;
}

export function CopyableText({ value, display, className }: CopyableTextProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = useCallback(() => {
    void navigator.clipboard.writeText(value).then(
      () => {
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 2000);
      },
      () => {
        // Clipboard API can be denied; fall back to the legacy path.
        const ta = document.createElement("textarea");
        ta.value = value;
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand("copy");
          setCopied(true);
          timer.current = setTimeout(() => setCopied(false), 2000);
        } finally {
          document.body.removeChild(ta);
        }
      },
    );
  }, [value]);

  return (
    <button
      type="button"
      onClick={copy}
      title={`复制：${value}`}
      className={`group inline-flex max-w-full items-center gap-1 rounded font-mono text-xs hover:bg-accent/40 ${className ?? ""}`}
    >
      <span className="truncate">{display ?? value}</span>
      {copied ? (
        <Check className="h-3 w-3 shrink-0 text-status-go" aria-hidden />
      ) : (
        <Copy
          className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
          aria-hidden
        />
      )}
      <span className="sr-only" role="status">
        {copied ? "已复制到剪贴板" : ""}
      </span>
    </button>
  );
}
