"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { ErrorMessage } from "../../components/ui/Alert";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from "recharts";
import type { BacktestResult } from "../../lib/types";

function fmtPct(v: unknown) {
  const n = parseFloat(String(v));
  return isNaN(n) ? "—" : `${n.toFixed(2)}%`;
}
function fmtNum(v: unknown, dec = 2) {
  const n = parseFloat(String(v));
  return isNaN(n) ? "—" : n.toFixed(dec);
}

export default function BacktestPage() {
  const histFetcher = useCallback(() => api.optimizationHistory(), []);
  const rankFetcher = useCallback(() => api.performanceRanking(), []);
  const btFetcher = useCallback(() => api.backtestResults(), []);

  const { data: histRes, loading: histLoading, error: histError } = useAutoRefresh(histFetcher, 30000);
  const { data: rankRes } = useAutoRefresh(rankFetcher, 30000);
  const { data: btRes } = useAutoRefresh(btFetcher, 30000);

  const runs = (histRes as { data: { runs: BacktestResult[] } } | null)?.data?.runs ?? [];
  const ranking = (rankRes as { data: { ranking: Array<{ signal_type: string; total_pnl: number; count: number; wins: number; win_rate: number }> } } | null)?.data?.ranking ?? [];

  const btData = (btRes as { data: unknown } | null)?.data;

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          {[
            { label: "Total Runs", value: runs.length },
            { label: "Best Win Rate", value: runs.length ? `${Math.max(...runs.map(r => Number(r.win_rate) || 0)).toFixed(1)}%` : "—" },
            { label: "Best PF", value: runs.length ? Math.max(...runs.map(r => Number(r.profit_factor) || 0)).toFixed(2) : "—" },
            { label: "Best Return", value: runs.length ? `${Math.max(...runs.map(r => Number(r.total_return) || 0)).toFixed(2)}%` : "—" },
          ].map((s) => (
            <div key={s.label} className="card">
              <p className="stat-label">{s.label}</p>
              <p style={{ fontSize: 26, fontWeight: 700, color: "var(--accent-blue)", marginTop: 6 }}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* Optimization History Table */}
        <Card title="Optimization Runs" subtitle="Stored backtest results">
          {histLoading ? <PageLoader /> : histError ? <ErrorMessage message={histError} /> : (
            <div style={{ overflowX: "auto" }}>
              <table className="table-dark">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Strategy</th>
                    <th>Return</th>
                    <th>Max DD</th>
                    <th>Sharpe</th>
                    <th>Win Rate</th>
                    <th>PF</th>
                    <th>Trades</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r, i) => {
                    const ret = Number(r.total_return) || 0;
                    const dd = Number(r.max_drawdown) || 0;
                    return (
                      <tr key={i}>
                        <td style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "monospace" }}>{r.filename}</td>
                        <td style={{ color: "var(--accent-blue)" }}>{String(r.strategy ?? "—")}</td>
                        <td style={{ color: ret >= 0 ? "var(--accent-green)" : "var(--accent-red)", fontWeight: 600 }}>{fmtPct(r.total_return)}</td>
                        <td style={{ color: dd < -5 ? "var(--accent-red)" : "var(--accent-yellow)" }}>{fmtPct(r.max_drawdown)}</td>
                        <td>{fmtNum(r.sharpe_ratio)}</td>
                        <td>{fmtPct(r.win_rate)}</td>
                        <td style={{ fontWeight: 600 }}>{fmtNum(r.profit_factor)}</td>
                        <td>{r.total_trades ?? "—"}</td>
                        <td style={{ fontSize: 11, color: "var(--text-muted)" }}>
                          {r.created ? new Date(r.created).toLocaleDateString() : "—"}
                        </td>
                      </tr>
                    );
                  })}
                  {!runs.length && (
                    <tr><td colSpan={9} style={{ textAlign: "center", color: "var(--text-muted)", padding: "40px 0" }}>
                      No backtest results found in results/ directory
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Signal Ranking */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card title="Signal Type Performance Ranking">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {ranking.map((r, i) => (
                <div key={i} style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 12px",
                  background: "var(--bg-secondary)",
                  borderRadius: 8,
                  border: "1px solid var(--border-subtle)",
                }}>
                  <span style={{
                    width: 24,
                    height: 24,
                    borderRadius: "50%",
                    background: i === 0 ? "#d4a843" : i === 1 ? "#94a3b8" : i === 2 ? "#cd7f32" : "var(--border)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 11,
                    fontWeight: 700,
                    color: i < 3 ? "#000" : "var(--text-muted)",
                    flexShrink: 0,
                  }}>{i + 1}</span>
                  <div style={{ flex: 1 }}>
                    <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{r.signal_type}</p>
                    <p style={{ fontSize: 11, color: "var(--text-muted)" }}>{r.count} trades · {r.win_rate}% WR</p>
                  </div>
                  <span style={{ fontSize: 14, fontWeight: 700, color: r.total_pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                    {r.total_pnl >= 0 ? "+" : ""}€{r.total_pnl.toFixed(0)}
                  </span>
                </div>
              ))}
              {!ranking.length && (
                <p style={{ textAlign: "center", color: "var(--text-muted)", padding: "30px 0", fontSize: 13 }}>
                  No signal performance data yet
                </p>
              )}
            </div>
          </Card>

          {/* Raw backtest data if available */}
          <Card title="Latest Backtest Data">
            <pre style={{
              fontSize: 11,
              color: "var(--text-secondary)",
              background: "var(--bg-secondary)",
              borderRadius: 8,
              padding: 12,
              overflow: "auto",
              maxHeight: 300,
              fontFamily: "monospace",
              lineHeight: 1.6,
            }}>
              {btData ? JSON.stringify(btData, null, 2).slice(0, 2000) : "No backtest data available.\nRun a backtest from strategy_backtest.py to populate."}
            </pre>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
