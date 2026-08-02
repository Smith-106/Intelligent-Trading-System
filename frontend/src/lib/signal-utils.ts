/**
 * P1 H5: 请求信号工具
 * - 默认 30s 超时（长任务可单独放宽）
 * - 支持多个信号合并（任意一个 abort 即中止）
 */

const DEFAULT_TIMEOUT = 30_000;

export function createTimeoutSignal(timeoutMs: number = DEFAULT_TIMEOUT): AbortSignal {
  return AbortSignal.timeout(timeoutMs);
}

export function mergeSignals(
  signals: AbortSignal[],
  fallbackTimeoutMs: number = DEFAULT_TIMEOUT,
): AbortSignal {
  if (signals.length === 0) return AbortSignal.timeout(fallbackTimeoutMs);
  if (signals.length === 1) return signals[0]!;
  return AbortSignal.any(signals);
}

export function isAborted(signal: AbortSignal): boolean {
  return signal.aborted;
}
