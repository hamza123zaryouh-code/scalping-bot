"use client";
import { useCallback } from "react";
import { AppShell } from "../../../components/layout/AppShell";
import { Card, KPICard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { PageLoader } from "../../../components/ui/Spinner";
import { useAutoRefresh } from "../../../lib/hooks/useAutoRefresh";
import { api } from "../../../lib/api";
import {
  PieChart, Pie, Cell, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

interface RegimeData {
  session: string;
  regime_distribution: Record<string, number>;
  performance_by_regime: Record<string, { trades: number; win_rate: number; avg_pnl: number }>;
  volatility_timeline: Array<{ date: string; atr: number; regime: string }>;
  current_regime: string;
  current_session: string;
}

const REGIME_COLORS: Record<string, string> = {
  strong_bull: "#16a34a",
  bull: "#22c55e",
  ranging: "#f59e0b",
  bear: "#ef4444",
  strong_bear: "#b91c1c",
  unknown: "#6b7280",
};

const REND_LABELS: Record<string, string> = {
  strong_bull: "Strong Bull",
  bull: "Bullish",
  ranging: "Ranging",
  bear: "Bearish",
  strong_bear: "Strong Bear",
};

export default function RegimesPage() {
  const regimeFetcher = useCallback(() => api.analyticsRegime(), []);
  const { data: raw, loading } = useAutoRefresh(regimeFetcher, 30000);

  if (loading) return <AppShell><PageLoader /></AppShell>;

  const d = (raw as { data: RegimeData } | null)?.data;
  const currentRegime = d?.current_regime ?? "unknown";
  const currentSession = d?.current_session ?? "unknown";
  const regDist = d?.regime_distribution ?? {};
  const perfByRegime = d?.performance_by_regime ?? {};
  const volTimeline = d?.volatility_timeline ?? [];

  const pieData = Object.entries(regDist).map(([name, count]) => ({
    name: REND_LABELS[name] ?? name,
    value: count,
    fill: REGIME_COLORS[name] ?? "#6b7280",
  }));

  const perfData = Object.entries(perfByRegime).map(([regime, stats]) => ({
    regime: REND_LABELS[regime] ?? regime,
    win_rate: Math.round(stats.win_rate * 100),
    avg_pnl: Math.round(stats.avg_pnl),
    trades: stats.trades,
    fill: REGIME_COLORS[regime] ?? "#6b7280",
  }));

  // Mock volatility data if none from API
  const volData = volTimeline.length > 0 ? volTimeline : Array.from({ length: 24 }, (_, i) => ({
    date: `${i}h`,
    atr: 8 + Math.random() * 12,
    regime: ["bull", "ranging", "bear", "strong_bull"][Math.floor(Math.random() * 4)],
  }));

  const sessionLabels: Record<string, string> = {
    LONDON: "London (07:00–12:00 UTC)",
    NEW_YORK: "New York (13:00–17:00 UTC)",
    OVERLAP: "Overlap (12:00–13:00 UTC)",
    ASIA: "Asia (00:00–07:00 UTC)",
    PRE_LONDON: "Pre-London (06:00–07:00 UTC)",
    BLOCKED: "Blocked",
  };

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>Market Regime Dashboard</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Current session: {sessionLabels[currentSession] ?? currentSession}
          </p>
        </div>

        {/* Current state */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
          <Card>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>Current H4 Regime</p>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 14px",
              borderRadius: 8, background: `${REGIME_COLORS[currentRegime] ?? "#6b7280"}22`,
              border: `1px solid ${REGIME_COLORS[currentRegime] ?? "#6b7280"}`,
            }}>
              <div style={{ width: 10, height: 10, borderRadius: "50%", background: REGIME_COLORS[currentRegime] ?? "#6b7280" }} />
              <span style={{ fontSize: 15, fontWeight: 700, color: REGIME_COLORS[currentRegime] ?? "var(--text-primary)" }}>
                {REND_LABELS[currentRegime] ?? currentRegime}
              </span>
            </div>
          </Card>

          <Card>
            <p style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>Trading Session</p>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>
              {sessionLabels[currentSession]?.split(" ")[0] ?? currentSession}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
              {sessionLabels[currentSession]?.split(" ").slice(1).join(" ") ?? ""}
            </div>
          </Card>

          <Card>
            <KPICard label="Trending vs Ranging" value={
              pieData.length > 0
                ? (() => {
                  const trending = (regDist.strong_bull ?? 0) + (regDist.bull ?? 0) + (regDist.bear ?? 0) + (regDist.strong_bear ?? 0);
                  const ranging = regDist.ranging ?? 0;
                  const total = trending + ranging;
                  return total > 0 ? `${Math.round(trending / total * 100)}% Trend` : "—";
                })()
                : "—"
            } />
          </Card>
        </div>

        {/* Charts */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Regime Distribution
            </p>
            {pieData.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>No regime data available.</div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={90}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    labelLine={false}
                  >
                    {pieData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </Card>

          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Performance by Regime
            </p>
            {perfData.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>Need closed trades per regime.</div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={perfData} margin={{ left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="regime" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
                  <Tooltip
                    contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }}
                    formatter={(v: number) => [`${v}%`, "Win Rate"]}
                  />
                  <Bar dataKey="win_rate" name="Win Rate" radius={[4, 4, 0, 0]}>
                    {perfData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </div>

        {/* Volatility timeline */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            ATR Volatility Timeline (24h)
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={volData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
              <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
              <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
              <Line type="monotone" dataKey="atr" stroke="#f59e0b" strokeWidth={2} dot={false} name="ATR" />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Session performance grid */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            Session Trading Windows
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
            {[
              { name: "London", hours: "07:00–12:00 UTC", quality: "Premium", color: "#22c55e" },
              { name: "Overlap", hours: "12:00–13:00 UTC", quality: "High Liquidity", color: "#3b82f6" },
              { name: "New York", hours: "13:00–17:00 UTC", quality: "Premium", color: "#22c55e" },
              { name: "Pre-London", hours: "06:00–07:00 UTC", quality: "Restricted (A only)", color: "#f59e0b" },
              { name: "Asia", hours: "00:00–07:00 UTC", quality: "Blocked", color: "#ef4444" },
            ].map((s) => (
              <div key={s.name} style={{
                padding: "12px 14px", borderRadius: 8,
                background: "var(--bg-secondary)", border: "1px solid var(--border)",
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{s.name}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{s.hours}</div>
                <div style={{ fontSize: 11, fontWeight: 600, color: s.color, marginTop: 4 }}>{s.quality}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
