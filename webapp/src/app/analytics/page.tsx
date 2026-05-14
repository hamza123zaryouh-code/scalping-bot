"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  ScatterChart, Scatter, PieChart, Pie, Legend,
} from "recharts";

function fmtEur(v: number) {
  return `€${v.toFixed(2)}`;
}

const COLORS = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ef4444", "#06b6d4"];

export default function AnalyticsPage() {
  const metricsFetcher = useCallback(() => api.analyticsMetrics(), []);
  const monthlyFetcher = useCallback(() => api.analyticsMonthly(), []);
  const sessionFetcher = useCallback(() => api.analyticsSession(), []);
  const regimeFetcher = useCallback(() => api.analyticsRegime(), []);

  const { data: metricsRes, loading } = useAutoRefresh(metricsFetcher, 30000);
  const { data: monthlyRes } = useAutoRefresh(monthlyFetcher, 30000);
  const { data: sessionRes } = useAutoRefresh(sessionFetcher, 30000);
  const { data: regimeRes } = useAutoRefresh(regimeFetcher, 30000);

  const metrics = (metricsRes as { data: Record<string, unknown> } | null)?.data ?? {};
  const monthly = (monthlyRes as { data: unknown } | null)?.data;
  const sessions = (sessionRes as { data: unknown } | null)?.data;
  const regime = (regimeRes as { data: unknown } | null)?.data;

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {loading ? <PageLoader /> : (
          <>
            {/* Core Metrics Grid */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
              {[
                { label: "Total P&L", key: "total_pnl", prefix: "€", color: "green" },
                { label: "Win Rate", key: "win_rate", suffix: "%", color: "blue" },
                { label: "Profit Factor", key: "profit_factor", color: "purple" },
                { label: "Avg Win", key: "avg_win", prefix: "€", color: "green" },
                { label: "Avg Loss", key: "avg_loss", prefix: "€", color: "red" },
                { label: "Best Trade", key: "best_trade", prefix: "€", color: "green" },
                { label: "Worst Trade", key: "worst_trade", prefix: "€", color: "red" },
                { label: "Total Trades", key: "total_trades", color: "default" },
              ].map((item) => {
                const raw = metrics[item.key];
                const value = raw !== undefined ? `${item.prefix ?? ""}${typeof raw === "number" ? raw.toFixed(2) : raw}${item.suffix ?? ""}` : "—";
                const colorMap: Record<string, string> = {
                  green: "var(--accent-green)",
                  red: "var(--accent-red)",
                  blue: "var(--accent-blue)",
                  purple: "var(--accent-purple)",
                  default: "var(--text-primary)",
                };
                return (
                  <div key={item.label} className="card">
                    <p className="stat-label">{item.label}</p>
                    <p style={{ fontSize: 22, fontWeight: 700, color: colorMap[item.color], marginTop: 6 }}>{value}</p>
                  </div>
                );
              })}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              {/* Session Analytics */}
              <Card title="Session P&L Analysis" subtitle="Performance by market session">
                {sessions && typeof sessions === "object" && !Array.isArray(sessions) ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {Object.entries(sessions as Record<string, unknown>).map(([session, data], i) => {
                      const d = data as Record<string, number>;
                      const pnl = d.total_pnl ?? 0;
                      return (
                        <div key={session} style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          padding: "10px 14px",
                          background: "var(--bg-secondary)",
                          borderRadius: 8,
                          border: "1px solid var(--border-subtle)",
                        }}>
                          <div>
                            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{session}</p>
                            <p style={{ fontSize: 11, color: "var(--text-muted)" }}>{d.count ?? 0} trades · {((d.win_rate ?? 0) * 100).toFixed(0)}% WR</p>
                          </div>
                          <span style={{ fontSize: 16, fontWeight: 700, color: pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                            {pnl >= 0 ? "+" : ""}{fmtEur(pnl)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
                    No session data available
                  </div>
                )}
              </Card>

              {/* Regime Analysis */}
              <Card title="Market Regime Analysis" subtitle="Performance by market condition">
                {regime && typeof regime === "object" && !Array.isArray(regime) ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {Object.entries(regime as Record<string, unknown>).map(([reg, data]) => {
                      const d = data as Record<string, number>;
                      const pnl = d.total_pnl ?? 0;
                      return (
                        <div key={reg} style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          padding: "10px 14px",
                          background: "var(--bg-secondary)",
                          borderRadius: 8,
                          border: "1px solid var(--border-subtle)",
                        }}>
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                              <Badge variant={reg === "trending" ? "green" : reg === "ranging" ? "yellow" : "gray"}>
                                {reg}
                              </Badge>
                            </div>
                            <p style={{ fontSize: 11, color: "var(--text-muted)" }}>{d.count ?? 0} trades</p>
                          </div>
                          <span style={{ fontSize: 16, fontWeight: 700, color: pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                            {pnl >= 0 ? "+" : ""}{fmtEur(pnl)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 13 }}>
                    No regime data available
                  </div>
                )}
              </Card>
            </div>

            {/* Monthly Breakdown */}
            <Card title="Monthly Performance Data">
              <pre style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                background: "var(--bg-secondary)",
                borderRadius: 8,
                padding: 12,
                overflow: "auto",
                maxHeight: 280,
                fontFamily: "monospace",
                lineHeight: 1.6,
              }}>
                {monthly ? JSON.stringify(monthly, null, 2).slice(0, 3000) : "No monthly data available"}
              </pre>
            </Card>

            {/* Full Metrics Dump */}
            <Card title="Full Analytics Report">
              <pre style={{
                fontSize: 11,
                color: "var(--text-secondary)",
                background: "var(--bg-secondary)",
                borderRadius: 8,
                padding: 12,
                overflow: "auto",
                maxHeight: 400,
                fontFamily: "monospace",
                lineHeight: 1.6,
              }}>
                {Object.keys(metrics).length > 0 ? JSON.stringify(metrics, null, 2) : "No analytics data available.\nStart trading to generate analytics."}
              </pre>
            </Card>
          </>
        )}
      </div>
    </AppShell>
  );
}
