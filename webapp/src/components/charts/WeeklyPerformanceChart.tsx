"use client";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { WeeklyBacktestSummary } from "../../lib/types";

interface Props {
  data: WeeklyBacktestSummary[];
  height?: number;
}

function formatEuro(value: number) {
  if (Math.abs(value) >= 1000) return `EUR ${(value / 1000).toFixed(1)}k`;
  return `EUR ${value.toFixed(0)}`;
}

export function WeeklyPerformanceChart({ data, height = 280 }: Props) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
        Geen weekdata beschikbaar
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
        <XAxis
          dataKey="week"
          tick={{ fontSize: 10, fill: "var(--text-muted)" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          yAxisId="eur"
          tick={{ fontSize: 10, fill: "var(--text-muted)" }}
          tickFormatter={formatEuro}
          axisLine={false}
          tickLine={false}
          width={60}
        />
        <YAxis
          yAxisId="pct"
          orientation="right"
          tick={{ fontSize: 10, fill: "var(--text-muted)" }}
          tickFormatter={(value) => `${Number(value).toFixed(1)}%`}
          axisLine={false}
          tickLine={false}
          width={46}
        />
        <Tooltip
          contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          formatter={(value, name) => {
            if (name === "pnl") return [`EUR ${Number(value).toFixed(2)}`, "Week PnL"];
            if (name === "return_pct") return [`${Number(value).toFixed(2)}%`, "Week Return"];
            if (name === "trades") return [String(value), "Trades"];
            return [String(value), String(name)];
          }}
          labelFormatter={(label) => `Week ${label}`}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <ReferenceLine yAxisId="eur" y={0} stroke="var(--border)" />
        <Bar yAxisId="eur" dataKey="pnl" name="Week PnL" radius={[4, 4, 0, 0]} maxBarSize={38}>
          {data.map((entry, index) => (
            <Cell key={index} fill={entry.pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)"} fillOpacity={0.9} />
          ))}
        </Bar>
        <Line
          yAxisId="pct"
          type="monotone"
          dataKey="return_pct"
          name="Week Return %"
          stroke="var(--accent-blue)"
          strokeWidth={2}
          dot={{ r: 2 }}
          activeDot={{ r: 4 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
