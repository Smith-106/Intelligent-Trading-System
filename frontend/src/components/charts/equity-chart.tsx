/**
 * 权益曲线 AreaChart — Recharts 实现。
 *
 * 主 Area: equity（primary 色渐变填充）；叠加 Line: cash / market_value（muted 色）。
 * 颜色使用 CSS 变量（var(--color-primary) 等），暗/亮主题自动兼容。
 */
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import type { Telemetry } from "./telemetry-helpers";
import { zipTelemetry, formatCompactNumber } from "./telemetry-helpers";

interface EquityChartProps {
  telemetry: Telemetry;
}

export function EquityChart({ telemetry }: EquityChartProps) {
  const rows = zipTelemetry(telemetry);

  if (rows.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center">
        <p className="text-sm text-muted-foreground">会话未运行，暂无权益序列</p>
      </div>
    );
  }

  return (
    <div className="h-[240px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-primary)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--color-primary)" stopOpacity={0.02} />
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
            tickFormatter={formatCompactNumber}
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
            formatter={(value: number | string | Array<number | string>, name: string) => {
              const num = typeof value === "number" ? value : Number(value);
              return [num.toLocaleString(undefined, { maximumFractionDigits: 2 }), name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area
            type="monotone"
            dataKey="equity"
            name="权益"
            stroke="var(--color-primary)"
            strokeWidth={2}
            fill="url(#equityGradient)"
            dot={false}
            activeDot={{ r: 3 }}
          />
          <Line
            type="monotone"
            dataKey="cash"
            name="现金"
            stroke="var(--color-muted-foreground)"
            strokeWidth={1}
            dot={false}
          />
          <Line
            type="monotone"
            dataKey="market_value"
            name="市值"
            stroke="var(--color-accent)"
            strokeWidth={1}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
