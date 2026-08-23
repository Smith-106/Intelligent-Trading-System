/**
 * Unified mutation feedback (REV-023-RV2).
 *
 * Before: five mutations spoke three dialects — toast+inline (session
 * start/stop), inline only with a success note that never cleared
 * (data-hub download), toast only for the most dangerous operation
 * (Kill Switch). This hook collapses them to one contract:
 *
 *   - toast  = instant awareness (auto-dismissing, works from anywhere)
 *   - inline = traceable detail, rendered by the caller via the returned
 *     `notice`; auto-clears after `inlineMs` or on the next attempt so a
 *     stale result can't outlive the form that produced it.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { useMutation } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";

import { useToast } from "@/hooks/use-toast";

export interface MutationFeedbackOptions<TData, TVars> {
  /** Toast + inline on success. */
  onSuccess?: {
    title: string;
    /** Static text or a function of the mutation result (e.g. rows_saved). */
    description?: string | ((data: TData) => string);
    variant?: "default" | "destructive";
  };
  /** Toast + inline on failure. */
  onError?: { title: string; description?: string | ((error: unknown) => string) };
  /**
   * Extra side effects (cache invalidation etc.) — run BEFORE feedback so a
   * synchronous re-render already sees fresh queries.
   */
  onSettledExtra?: () => void;
  /** Inline notice lifetime in ms; 0 disables auto-clear. Default 8000. */
  inlineMs?: number;
  /** Escape hatch for callers needing the raw result (e.g. rows_saved). */
  mutate?: Parameters<ReturnType<typeof useMutation<TData, Error, TVars>>["mutate"]>[0];
}

export interface InlineNotice {
  kind: "success" | "error";
  title: string;
  detail?: string;
}

export interface MutationFeedback<TData, TVars> {
  mutation: UseMutationResult<TData, Error, TVars>;
  /** Present while an inline message should be rendered. */
  notice: InlineNotice | null;
  /** Dismiss the inline notice early (e.g. form change). */
  dismissNotice: () => void;
}

export function useMutationFeedback<TData, TVars = void>(
  options: MutationFeedbackOptions<TData, TVars> & {
    mutationFn: (vars: TVars) => Promise<TData>;
  },
):
  MutationFeedback<TData, TVars> & {
    mutate: UseMutationResult<TData, Error, TVars>["mutate"];
    mutateAsync: UseMutationResult<TData, Error, TVars>["mutateAsync"];
  } {
  const { mutationFn, onSuccess, onError, onSettledExtra, inlineMs = 8000 } = options;
  const { toast } = useToast();
  const [notice, setNotice] = useState<InlineNotice | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const scheduleClear = useCallback(
    (delay: number) => {
      clearTimer();
      if (delay > 0) timer.current = setTimeout(() => setNotice(null), delay);
    },
    [clearTimer],
  );

  useEffect(() => clearTimer, [clearTimer]);

  const dismissNotice = useCallback(() => {
    clearTimer();
    setNotice(null);
  }, [clearTimer]);

  const mutation = useMutation<TData, Error, TVars>({
    mutationFn,
    onSuccess: (data) => {
      onSettledExtra?.();
      if (onSuccess) {
        const detail =
          typeof onSuccess.description === "function"
            ? onSuccess.description(data)
            : onSuccess.description;
        setNotice({ kind: "success", title: onSuccess.title, detail });
        scheduleClear(inlineMs);
        toast({
          title: onSuccess.title,
          description: detail || undefined,
          variant: onSuccess.variant,
        });
      }
      return data;
    },
    onError: (error) => {
      onSettledExtra?.();
      if (onError) {
        const detail =
          typeof onError.description === "function"
            ? onError.description(error)
            : (onError.description ?? error.message);
        setNotice({ kind: "error", title: onError.title, detail });
        // Errors stay until dismissed/next attempt — auto-clear only successes.
        toast({
          title: onError.title,
          description: typeof detail === "string" ? detail : undefined,
          variant: "destructive",
        });
      }
    },
  });

  return {
    mutation,
    mutate: mutation.mutate,
    mutateAsync: mutation.mutateAsync,
    notice,
    dismissNotice,
  };
}
