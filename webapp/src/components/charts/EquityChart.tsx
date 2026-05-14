"use client";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
import type { EquityPoint } from "../../lib/types";

interface Props {
  data: EquityPoint[];
  startingCapital?: number;
  height?: number;
}

function fmt(v: number) {
  if (v >= 1000) return `€${(v / 1000).toFixed(0)}k`;
  return `€${v.toFixed(0)}`;
}

export function EquityChart({ data, startingCapital = 160000, height = 220 }: Props) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
        No equity data yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
        <XAxis
          dataKey="time"
          tick={{ fontSize: 10, fill: "var(--text-muted)" }}
          tickFormatter={(v) => {
            try { return new Date(v).toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
            catch { return ""; }
          }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "var(--text-muted)" }}
          tickFormatter={fmt}
          axisLine={false}
          tickLine={false}
          width={48}
        />
        <Tooltip
          contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "var(--text-secondary)" }}
          formatter={(v) => [`€${Number(v).toFixed(2)}`, "Equity"]}
          labelFormatter={(l) => {
            try { return new Date(l).toLocaleString(); } catch { return l; }
          }}
        />
        <ReferenceLine y={startingCapital} stroke="rgba(245,158,11,0.4)" strokeDasharray="4 4" />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="#3b82f6"
          strokeWidth={2}
          fill="url(#equityGradient)"
          dot={false}
          activeDot={{ r: 4, fill: "#3b82f6" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
