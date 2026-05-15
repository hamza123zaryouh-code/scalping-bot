"use client";
import { useCallback } from "react";
import { AppShell } from "../../../components/layout/AppShell";
import { Card, KPICard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { PageLoader } from "../../../components/ui/Spinner";
import { useAutoRefresh } from "../../../lib/hooks/useAutoRefresh";
import { api } from "../../../lib/api";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, ScatterChart, Scatter, ZAxis,
} from "recharts";

interface PatternRecord {
  key: string;
  signal_type: string;
  direction: string;
  h4_regime: string;
  d1_trend: string;
  rsi_bucket: string;
  session: string;
  trades: number;
  wins: number;
  total_pnl: number;
  win_rate: number;
  avg_pnl: number;
  avg_rr: number;
  quality_score: number;
  risk_multiplier: number;
  is_blocked: boolean;
  is_boosted: boolean;
  last_trade_at: string;
}

interface PatternsData {
  patterns: PatternRecord[];
  total_patterns: number;
  boosted_patterns: number;
  blocked_patterns: number;
  patterns_with_data: number;
  avg_win_rate: number;
}

function WinRateBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct >= 60 ? "#22c55e" : pct >= 45 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, color, fontWeight: 600, minWidth: 32 }}>{pct}%</span>
    </div>
  );
}

export default function PatternsPage() {
  const patFetcher = useCallback(() => api.analyticsRegime(), []);
  const { data: raw, loading } = useAutoRefresh(patFetcher, 60000);

  if (loading) return <AppShell><PageLoader /></AppShell>;

  // Read patterns from the analytics/regime endpoint or memory endpoint
  const patternsData = (raw as { data: PatternsData } | null)?.data;
  const patterns: PatternRecord[] = patternsData?.patterns ?? [];

  const topPatterns = [...patterns]
    .filter((p) => p.trades >= 3 && !p.is_blocked)
    .sort((a, b) => b.quality_score - a.quality_score)
    .slice(0, 15);

  const blockedPatterns = patterns.filter((p) => p.is_blocked);
  const boostedPatterns = patterns.filter((p) => p.is_boosted);

  // Win rate distribution by signal type
  const signalTypeMap: Record<string, { wins: number; trades: number }> = {};
  for (const p of patterns) {
    if (!signalTypeMap[p.signal_type]) signalTypeMap[p.signal_type] = { wins: 0, trades: 0 };
    signalTypeMap[p.signal_type].wins += p.wins;
    signalTypeMap[p.signal_type].trades += p.trades;
  }
  const signalChart = Object.entries(signalTypeMap)
    .map(([type, d]) => ({
      type,
      win_rate: d.trades > 0 ? parseFloat(((d.wins / d.trades) * 100).toFixed(1)) : 0,
      trades: d.trades,
    }))
    .sort((a, b) => b.win_rate - a.win_rate);

  // Scatter: quality score vs win rate
  const scatterData = topPatterns.map((p) => ({
    x: Math.round(p.win_rate * 100),
    y: parseFloat(p.quality_score.toFixed(2)),
    z: Math.max(4, p.trades * 2),
    name: `${p.signal_type} ${p.direction}`,
  }));

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>Pattern Memory</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {patterns.length} setups tracked · {boostedPatterns.length} boosted · {blockedPatterns.length} blocked
          </p>
        </div>

        {/* KPI row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <Card><KPICard label="Total Patterns" value={String(patternsData?.total_patterns ?? patterns.length)} /></Card>
          <Card><KPICard label="Boosted" value={String(patternsData?.boosted_patterns ?? boostedPatterns.length)} trend="up" /></Card>
          <Card><KPICard label="Blocked" value={String(patternsData?.blocked_patterns ?? blockedPatterns.length)} trend="down" /></Card>
          <Card><KPICard label="Avg Win Rate" value={`${((patternsData?.avg_win_rate ?? 0) * 100).toFixed(1)}%`} /></Card>
        </div>

        {/* Charts */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Win Rate by Signal Type
            </p>
            {signalChart.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>
                No pattern data yet. Trades needed to build memory.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={signalChart} margin={{ left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="type" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
                  <Tooltip
                    contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }}
                    formatter={(v: number) => [`${v}%`, "Win Rate"]}
                  />
                  <Bar dataKey="win_rate" radius={[4, 4, 0, 0]}>
                    {signalChart.map((entry, i) => (
                      <Cell key={i} fill={entry.win_rate >= 60 ? "#22c55e" : entry.win_rate >= 45 ? "#f59e0b" : "#ef4444"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Quality Score vs Win Rate
            </p>
            {scatterData.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>
                Requires ≥5 trades per pattern.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <ScatterChart margin={{ left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="x" name="Win Rate %" domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
                  <YAxis dataKey="y" name="Quality Score" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                  <ZAxis dataKey="z" range={[40, 200]} />
                  <Tooltip
                    contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }}
                    formatter={(v: number, name: string) => [name === "Win Rate %" ? `${v}%` : v.toFixed(2), name]}
                  />
                  <Scatter data={scatterData} fill="#3b82f6" fillOpacity={0.7} />
                </ScatterChart>
              </ResponsiveContainer>
            )}
          </Card>
        </div>

        {/* Top patterns table */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            Top Performing Setups
          </p>
          {topPatterns.length === 0 ? (
            <div style={{ textAlign: "center", padding: "30px 0", color: "var(--text-muted)", fontSize: 13 }}>
              Pattern data builds automatically as trades close. Need ≥3 trades per setup.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
                    {["Signal", "Dir", "Regime", "Session", "Trades", "Win Rate", "Avg RR", "Quality", "Multiplier"].map((h) => (
                      <th key={h} style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {topPatterns.map((p, i) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "8px 10px", fontWeight: 600, color: "var(--text-primary)" }}>{p.signal_type}</td>
                      <td style={{ padding: "8px 10px" }}>
                        <Badge variant={p.direction === "buy" ? "success" : "danger"}>{p.direction.toUpperCase()}</Badge>
                      </td>
                      <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>{p.h4_regime}</td>
                      <td style={{ padding: "8px 10px", color: "var(--text-muted)" }}>{p.session}</td>
                      <td style={{ padding: "8px 10px" }}>{p.trades}</td>
                      <td style={{ padding: "8px 10px", minWidth: 100 }}><WinRateBar rate={p.win_rate} /></td>
                      <td style={{ padding: "8px 10px" }}>{p.avg_rr.toFixed(2)}</td>
                      <td style={{ padding: "8px 10px", color: "#3b82f6", fontWeight: 600 }}>{p.quality_score.toFixed(3)}</td>
                      <td style={{ padding: "8px 10px" }}>
                        <span style={{
                          fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                          background: p.risk_multiplier >= 1 ? "#dcfce7" : "#fef2f2",
                          color: p.risk_multiplier >= 1 ? "#16a34a" : "#dc2626",
                        }}>
                          {(p.risk_multiplier * 100).toFixed(0)}%
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Blocked patterns */}
        {blockedPatterns.length > 0 && (
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "#ef4444", marginBottom: 12 }}>
              Blocked Patterns ({blockedPatterns.length})
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
              {blockedPatterns.map((p, i) => (
                <div key={i} style={{
                  padding: "10px 12px", borderRadius: 8,
                  background: "#fef2f2", border: "1px solid #fecaca",
                }}>
                  <div style={{ fontWeight: 700, fontSize: 12, color: "#dc2626" }}>{p.signal_type} {p.direction.toUpperCase()}</div>
                  <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
                    {p.trades} trades · {Math.round(p.win_rate * 100)}% WR · {p.h4_regime}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
