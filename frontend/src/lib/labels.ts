/**
 * Central enum -> Chinese label maps (REV-022-RV3/RV4).
 *
 * Panels previously inlined raw backend enums (`long`/`buy`/`paper`/
 * `demo-seeded`...) into a Chinese UI, and "数据模式" had TWO diverging
 * word lists (overview vs data-hub). All badge-facing translations live
 * here now; unknown values fall through to the raw string so new backend
 * enums degrade visibly instead of silently.
 */

export function labelFor(map: Record<string, string>, value: string | undefined | null): string {
  if (!value) return "-";
  return map[value] ?? value;
}

/** Session/execution mode. */
export const MODE_LABELS: Record<string, string> = {
  paper: "模拟盘",
  live: "实盘",
};

/** Position / order direction. */
export const SIDE_LABELS: Record<string, string> = {
  long: "做多",
  short: "做空",
  buy: "买入",
  sell: "卖出",
};

/** Order lifecycle status. */
export const ORDER_STATUS_LABELS: Record<string, string> = {
  open: "挂单中",
  filled: "已成交",
  partially_filled: "部分成交",
  canceled: "已撤销",
  cancelled: "已撤销",
  rejected: "已拒绝",
  expired: "已过期",
};

/** Order type. */
export const ORDER_TYPE_LABELS: Record<string, string> = {
  market: "市价单",
  limit: "限价单",
  stop: "止损单",
  stop_limit: "止损限价",
};

/** Event severity levels. */
export const LEVEL_LABELS: Record<string, string> = {
  info: "信息",
  warning: "警告",
  error: "错误",
  critical: "严重",
};

/**
 * Unified data-mode vocabulary (merges overview's and data-hub's two
 * divergent maps; matches service.py's data_mode values).
 */
export const DATA_MODE_LABELS: Record<string, string> = {
  market: "实时数据",
  live: "实时数据",
  parquet: "本地数据",
  "demo-seeded": "演示数据",
  demo: "演示数据",
  hybrid: "混合数据",
  mixed: "混合数据",
  "source-unknown": "来源未标注",
};
