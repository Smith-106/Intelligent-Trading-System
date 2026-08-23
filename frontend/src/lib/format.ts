/**
 * Unified formatting helpers (REV-023).
 *
 * Before this module the UI had four coexisting time formats (time-only
 * events that can't be told apart across days, date-only history rows that
 * can't be ordered within a day, a no-locale toLocaleTimeString, and
 * relative/absolute mixed in one column) plus drifting numeric precisions
 * (drawdown at 1, 2 and chart-local precision; metrics always .toFixed(4)).
 */

/** `MM-dd HH:mm` — events & history: sortable within a day, distinguishable across days. */
export function fmtDateTime(value: string | number | Date): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** `yyyy-MM-dd` — pure dates. */
export function fmtDate(value: string | number | Date | null): string {
  if (value == null) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("sv-SE"); // ISO-style yyyy-MM-dd
}

/** Relative age from an ISO captured_at — "刚刚" / "N 秒前" / "N 分前". */
export function fmtDataAge(capturedAt: string | undefined | null): string {
  if (!capturedAt) return "";
  const then = new Date(capturedAt).getTime();
  if (Number.isNaN(then)) return "";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 10) return "刚刚";
  if (sec < 60) return `${sec} 秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分前`;
  return `${Math.floor(min / 60)} 时前`;
}

/** Money with grouped thousands, at most 2 fraction digits. */
export function fmtMoney(value: number | undefined | null): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

/** Percentage from a fraction (0.0234 -> "2.34%"). Default 2-digit precision everywhere. */
export function fmtPct(fraction: number | undefined | null, digits = 2): string {
  if (fraction == null || !Number.isFinite(fraction)) return "-";
  return `${(fraction * 100).toFixed(digits)}%`;
}
