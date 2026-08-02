/**
 * Telemetry 数据转换 helper — 将后端并行数组格式转为 Recharts 行对象。
 *
 * 后端 /api/execution 的 telemetry 字段使用并行数组（labels[] + 各指标序列），
 * Recharts 需要 Array<Record> 行格式，此模块负责 zip 转换与防御性截断。
 */
import type { ExecutionSnapshot } from "@/lib/api-client";

export type Telemetry = ExecutionSnapshot["telemetry"];

export interface TelemetryRow {
  label: string;
  equity: number;
  cash: number;
  market_value: number;
  /** 百分比形式（0.05 → 5） */
  drawdown: number;
  open_positions: number;
  pending_orders: number;
}

/**
 * 以 labels[] 为轴，zip 各并行序列为行对象数组。
 *
 * 防御策略：
 * - point_count === 0 或 labels 缺失/为空 → 返回 []
 * - 各序列长度与 labels 不一致时按最短截断
 */
export function zipTelemetry(telemetry: Telemetry): TelemetryRow[] {
  if (!telemetry || telemetry.point_count === 0 || !telemetry.labels || telemetry.labels.length === 0) {
    return [];
  }

  const len = Math.min(
    telemetry.labels.length,
    telemetry.equity?.length ?? 0,
    telemetry.cash?.length ?? 0,
    telemetry.market_value?.length ?? 0,
    telemetry.drawdown?.length ?? 0,
    telemetry.open_positions?.length ?? 0,
    telemetry.pending_orders?.length ?? 0,
  );

  if (len === 0) return [];

  const rows: TelemetryRow[] = [];
  for (let i = 0; i < len; i++) {
    rows.push({
      label: telemetry.labels[i] ?? "",
      equity: telemetry.equity[i] ?? 0,
      cash: telemetry.cash[i] ?? 0,
      market_value: telemetry.market_value[i] ?? 0,
      drawdown: drawdownPercent(telemetry.drawdown[i] ?? 0),
      open_positions: telemetry.open_positions[i] ?? 0,
      pending_orders: telemetry.pending_orders[i] ?? 0,
    });
  }
  return rows;
}

/** 回撤小数 → 百分比（0.05 = 5%） */
export function drawdownPercent(v: number): number {
  return v * 100;
}

/** 大数紧凑格式化（权益轴刻度用），如 123456 → "123.5K" */
export function formatCompactNumber(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toFixed(0);
}
