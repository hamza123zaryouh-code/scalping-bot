"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import {
  ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
} from "recharts";
import type { SignalTypeRanking, SessionPerformance } from "../../lib/types";

export default function OptimizerPage() {
  const rankFetcher = useCallback(() => api.performanceRanking(), []);
  const sessionFetcher = useCallback(() => api.sessionAnalysis(), []);
  const bestParamsFetcher = useCallback(() => api.bestParameters(), []);
  const histFetcher = useCallback(() => api.optimizationHistory(), []);

  const { data: rankRes } = useAutoRefresh(rankFetcher, 30000);
  const { data: sessionRes } = useAutoRefresh(sessionFetcher, 30000);
  const { data: paramsRes } = useAutoRefresh(bestParamsFetcher, 60000);
  const { data: histRes } = useAutoRefresh(histFetcher, 60000);

  const ranking: SignalTypeRanking[] = (rankRes as { data: { ranking: SignalTypeRanking[] } } | null)?.data?.ranking ?? [];
  const sessions: SessionPerformance[] = (sessionRes as { data: { sessions: SessionPerformance[] } } | null)?.data?.sessions ?? [];
  const params = (paramsRes as { data: { parameters: unknown } } | null)?.data?.parameters;
  const runs = (histRes as { data: { runs: unknown[]; total: number } } | null)?.data?.runs ?? [];

  const radarData = ranking.slice(0, 6).map((r) => ({
    subject: r.signal_type?.replace(/_/g, " ") ?? "Unknown",
    winRate: r.win_rate,
    pnl: Math.max(r.total_pnl / 100, 0),
    count: r.count,
  }));

  const sessionColors: Record<string, string> = {
    "Asian": "#8b5cf6",
    "London Open": "#3b82f6",
    "NY Open": "#10b981",
    "NY Afternoon": "#f59e0b",
    "After Hours": "#6b7280",
  };

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          {[
            { label: "Signal Types Tracked", value: ranking.length },
            { label: "Sessions Analyzed", value: sessions.length },
            { label: "Optimization Runs", value: runs.length },
            { label: "Top Signal", value: ranking[0]?.signal_type?.replace(/_/g, " ") ?? "—" },
          ].map((s) => (
            <div key={s.label} className="card">
              <p className="stat-label">{s.label}</p>
              <p style={{ fontSize: s.label === "Top Signal" ? 16 : 26, fontWeight: 700, color: "var(--accent-purple)", marginTop: 6 }}>{s.value}</p>
            </div>
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* Signal Radar */}
          <Card title="Signal Performance Radar">
            {radarData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="var(--border)" />
                  <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                  <PolarRadiusAxis angle={30} tick={{ fontSize: 8, fill: "var(--text-muted)" }} />
                  <Radar name="Win Rate" dataKey="winRate" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.2} />
                </RadarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: 260, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
                No signal data yet
              </div>
            )}
          </Card>

          {/* Session Performance */}
          <Card title="Session Performance" subtitle="P&L by trading session">
            {sessions.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={sessions} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="session" tick={{ fontSize: 11, fill: "var(--text-secondary)" }} axisLine={false} tickLine={false} width={90} />
                  <Tooltip
                    contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                    formatter={(v, name) => {
                      if (name === "total_pnl") return [`€${Number(v).toFixed(2)}`, "P&L"];
                      if (name === "win_rate") return [`${Number(v).toFixed(1)}%`, "Win Rate"];
                      return [`${v}`, String(name)];
                    }}
                  />
                  <Bar dataKey="total_pnl" radius={[0, 4, 4, 0]} maxBarSize={24}>
                    {sessions.map((s, i) => (
                      <Cell key={i} fill={sessionColors[s.session] ?? "#6b7280"} fillOpacity={0.85} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: 260, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
                No session data yet
              </div>
            )}
          </Card>
        </div>

        {/* Signal Ranking Table */}
        <Card title="Signal Type Ranking" subtitle="Sorted by total P&L">
          <div style={{ overflowX: "auto" }}>
            <table className="table-dark">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Signal Type</th>
                  <th>Total P&L</th>
                  <th>Trades</th>
                  <th>Wins</th>
                  <th>Win Rate</th>
                  <th>Rating</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map((r, i) => (
                  <tr key={i}>
                    <td style={{ color: i === 0 ? "#d4a843" : i === 1 ? "#94a3b8" : i === 2 ? "#cd7f32" : "var(--text-muted)", fontWeight: 700 }}>
                      {i + 1}
                    </td>
                    <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                      {r.signal_type?.replace(/_/g, " ")}
                    </td>
                    <td style={{ fontWeight: 700, color: r.total_pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                      {r.total_pnl >= 0 ? "+" : ""}€{r.total_pnl.toFixed(2)}
                    </td>
                    <td>{r.count}</td>
                    <td style={{ color: "var(--accent-green)" }}>{r.wins}</td>
                    <td>
                      <span style={{ color: r.win_rate >= 60 ? "var(--accent-green)" : r.win_rate >= 45 ? "var(--accent-yellow)" : "var(--accent-red)", fontWeight: 600 }}>
                        {r.win_rate.toFixed(1)}%
                      </span>
                    </td>
                    <td>
                      <Badge variant={r.win_rate >= 60 && r.total_pnl > 0 ? "green" : r.win_rate >= 45 ? "yellow" : "red"}>
                        {r.win_rate >= 60 && r.total_pnl > 0 ? "STRONG" : r.win_rate >= 45 ? "NEUTRAL" : "WEAK"}
                      </Badge>
                    </td>
                  </tr>
                ))}
                {!ranking.length && (
                  <tr><td colSpan={7} style={{ textAlign: "center", color: "var(--text-muted)", padding: "40px 0" }}>
                    No trade data to rank. Execute trades to populate.
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Best Parameters */}
        <Card title="Best Parameters" subtitle="Saved from optimization runs">
          <pre style={{
            fontSize: 12,
            color: "var(--text-secondary)",
            background: "var(--bg-secondary)",
            borderRadius: 8,
            padding: 14,
            overflow: "auto",
            maxHeight: 300,
            fontFamily: "monospace",
            lineHeight: 1.7,
          }}>
            {params ? JSON.stringify(params, null, 2) : "No best parameters saved yet.\nRun strategy_v16.py optimizer to store results."}
          </pre>
        </Card>
      </div>
    </AppShell>
  );
}
