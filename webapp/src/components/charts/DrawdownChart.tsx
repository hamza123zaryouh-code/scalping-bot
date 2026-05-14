"use client";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
import type { DrawdownPoint } from "../../lib/types";

interface Props {
  data: DrawdownPoint[];
  height?: number;
  maxAllowed?: number;
}

export function DrawdownChart({ data, height = 180, maxAllowed = -6 }: Props) {
  if (!data || data.length === 0) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
        No drawdown data yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#ef4444" stopOpacity={0.02} />
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
          tickFormatter={(v) => `${v.toFixed(1)}%`}
          axisLine={false}
          tickLine={false}
          width={44}
        />
        <Tooltip
          contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          formatter={(v) => [`${Number(v).toFixed(2)}%`, "Drawdown"]}
          labelFormatter={(l) => {
            try { return new Date(l).toLocaleString(); } catch { return l; }
          }}
        />
        <ReferenceLine y={maxAllowed} stroke="rgba(239,68,68,0.6)" strokeDasharray="4 4" label={{ value: "Max DD", fill: "#f87171", fontSize: 10 }} />
        <Area
          type="monotone"
          dataKey="drawdown_pct"
          stroke="#ef4444"
          strokeWidth={2}
          fill="url(#ddGradient)"
          dot={false}
          activeDot={{ r: 4, fill: "#ef4444" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
