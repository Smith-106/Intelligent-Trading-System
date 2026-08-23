/**
 * 回撤曲线 AreaChart — Recharts 实现。
 *
 * drawdown 经 zipTelemetry 已转为百分比（0.05 → 5）。
 * Area 使用 status-danger 色，正值 = 回撤幅度。
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Telemetry } from "./telemetry-helpers";
import { zipTelemetry } from "./telemetry-helpers";
import { fmtPct } from "@/lib/format";

interface DrawdownChartProps {
  telemetry: Telemetry;
}

export function DrawdownChart({ telemetry }: DrawdownChartProps) {
  const rows = zipTelemetry(telemetry);

  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center">
        <p className="text-sm text-muted-foreground">会话未运行，暂无回撤序列</p>
      </div>
    );
  }

  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-status-danger)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--color-status-danger)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            interval="preserveStartEnd"
            tickLine={false}
            axisLine={{ stroke: "var(--color-border)" }}
          />
          <YAxis
            // hy3 RV-008：drawdown 序列已在 zipTelemetry 中转为百分比（0.05→5），
            // 故先 /100 还原为小数交给 fmtPct 格式化，避免直接 fmtPct 产生 500% 百倍误差。
            tickFormatter={(v: number) => fmtPct(Math.abs(v) / 100, 1)}
            tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--color-card)",
              border: "1px solid var(--color-border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--color-foreground)",
            }}
            formatter={(value: number | string | Array<number | string>) => {
              const num = typeof value === "number" ? value : Number(value);
              return [`${num.toFixed(2)}%`, "回撤"];
            }}
          />
          <Area
            type="monotone"
            dataKey="drawdown"
            name="回撤"
            stroke="var(--color-status-danger)"
            strokeWidth={2}
            fill="url(#drawdownGradient)"
            dot={false}
            activeDot={{ r: 3 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
