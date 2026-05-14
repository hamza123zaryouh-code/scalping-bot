"use client";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ReferenceLine } from "recharts";
import type { MonthlyPnL } from "../../lib/types";

interface Props {
  data: MonthlyPnL[];
  height?: number;
}

export function MonthlyPnLChart({ data, height = 220 }: Props) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
        No monthly data yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
        <XAxis dataKey="month" tick={{ fontSize: 10, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--text-muted)" }}
          tickFormatter={(v) => `€${(v / 1000).toFixed(0)}k`}
          axisLine={false}
          tickLine={false}
          width={44}
        />
        <Tooltip
          contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          formatter={(v, name) => {
            if (name === "pnl") return [`€${Number(v).toFixed(2)}`, "P&L"];
            return [`${v}`, String(name)];
          }}
        />
        <ReferenceLine y={0} stroke="var(--border)" />
        <Bar dataKey="pnl" radius={[4, 4, 0, 0]} maxBarSize={40}>
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)"} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
