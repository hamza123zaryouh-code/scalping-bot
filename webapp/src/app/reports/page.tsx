"use client";
import { useCallback, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import { MonthlyPnLChart } from "../../components/charts/MonthlyPnLChart";
import { EquityChart } from "../../components/charts/EquityChart";
import type { MonthlyPnL, EquityPoint } from "../../lib/types";

function fmtEur(v: number) {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", minimumFractionDigits: 2 }).format(v);
}

function ReportFiles({ dir, label }: { dir: string; label: string }) {
  return (
    <div>
      <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 10 }}>
        {label}
      </p>
      <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>
        Reports are automatically generated and saved to <code style={{ fontFamily: "monospace", color: "var(--accent-blue)", background: "rgba(59,130,246,0.1)", padding: "1px 5px", borderRadius: 4 }}>/{dir}</code> directory.
      </p>
    </div>
  );
}

export default function ReportsPage() {
  const monthlyFetcher = useCallback(() => api.monthlyPnL(), []);
  const equityFetcher = useCallback(() => api.equityCurve(), []);
  const historyFetcher = useCallback(() => api.tradeHistory(1000), []);
  const dashFetcher = useCallback(() => api.dashboard(), []);

  const { data: monthlyRes } = useAutoRefresh(monthlyFetcher, 60000);
  const { data: equityRes } = useAutoRefresh(equityFetcher, 60000);
  const { data: histRes, loading } = useAutoRefresh(historyFetcher, 60000);
  const { data: dashRes } = useAutoRefresh(dashFetcher, 10000);

  const months: MonthlyPnL[] = (monthlyRes as { data: { months: MonthlyPnL[] } } | null)?.data?.months ?? [];
  const equityPoints: EquityPoint[] = (equityRes as { data: { points: EquityPoint[] } } | null)?.data?.points ?? [];
  const hist = (histRes as { data: { trades: Array<{ pnl: number; signal_type: string; side: string; opened_at: string }>; total: number; wins: number; losses: number; total_pnl: number; profit_factor: number; win_rate: number } } | null)?.data;
  const dash = (dashRes as { data: { account: { balance: number; equity: number; daily_pnl: number }; performance: { total_pnl: number; win_rate: number; profit_factor: number; total_trades: number } } } | null)?.data;

  const totalPnL = hist?.total_pnl ?? 0;
  const avgPerTrade = hist?.total && hist.total > 0 ? totalPnL / hist.total : 0;
  const bestMonth = months.length ? Math.max(...months.map(m => m.pnl)) : 0;
  const worstMonth = months.length ? Math.min(...months.map(m => m.pnl)) : 0;

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Performance Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          {[
            { label: "Total P&L", value: fmtEur(totalPnL), color: totalPnL >= 0 ? "green" : "red" },
            { label: "Win Rate", value: `${hist?.win_rate ?? 0}%`, color: "blue" },
            { label: "Profit Factor", value: (hist?.profit_factor ?? 0).toFixed(2), color: "purple" },
            { label: "Total Trades", value: hist?.total ?? 0, color: "default" },
            { label: "Avg Per Trade", value: fmtEur(avgPerTrade), color: avgPerTrade >= 0 ? "green" : "red" },
            { label: "Best Month", value: fmtEur(bestMonth), color: "green" },
            { label: "Worst Month", value: fmtEur(worstMonth), color: "red" },
            { label: "Active Months", value: months.length, color: "default" },
          ].map((s) => {
            const colorMap: Record<string, string> = { green: "var(--accent-green)", red: "var(--accent-red)", blue: "var(--accent-blue)", purple: "var(--accent-purple)", default: "var(--text-primary)" };
            return (
              <div key={s.label} className="card">
                <p className="stat-label">{s.label}</p>
                <p style={{ fontSize: 20, fontWeight: 700, color: colorMap[s.color], marginTop: 6 }}>{s.value}</p>
              </div>
            );
          })}
        </div>

        {/* Charts */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card title="Equity Curve — Full History">
            <EquityChart data={equityPoints} startingCapital={160000} height={220} />
          </Card>
          <Card title="Monthly P&L Breakdown">
            <MonthlyPnLChart data={months} height={220} />
          </Card>
        </div>

        {/* Monthly Table */}
        <Card title="Monthly Report Table" subtitle="Full breakdown">
          <div style={{ overflowX: "auto" }}>
            <table className="table-dark">
              <thead>
                <tr>
                  <th>Month</th>
                  <th>P&L</th>
                  <th>Trades</th>
                  <th>Win Rate</th>
                  <th>Return %</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {months.slice().reverse().map((m, i) => {
                  const returnPct = (m.pnl / 160000 * 100);
                  return (
                    <tr key={i}>
                      <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>{m.month}</td>
                      <td style={{ fontWeight: 700, color: m.pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                        {m.pnl >= 0 ? "+" : ""}{fmtEur(m.pnl)}
                      </td>
                      <td>{m.trades}</td>
                      <td style={{ color: m.win_rate >= 50 ? "var(--accent-green)" : "var(--accent-red)" }}>
                        {m.win_rate.toFixed(1)}%
                      </td>
                      <td style={{ color: returnPct >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                        {returnPct >= 0 ? "+" : ""}{returnPct.toFixed(2)}%
                      </td>
                      <td>
                        <Badge variant={m.pnl >= 8000 ? "green" : m.pnl >= 0 ? "blue" : "red"}>
                          {m.pnl >= 8000 ? "TARGET MET" : m.pnl >= 0 ? "PROFIT" : "LOSS"}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
                {!months.length && (
                  <tr><td colSpan={6} style={{ textAlign: "center", color: "var(--text-muted)", padding: "40px 0" }}>
                    No monthly data available yet
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Auto Logging Info */}
        <Card title="Automatic Data Logging" subtitle="All data is saved continuously">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            <div style={{ padding: 16, background: "var(--bg-secondary)", borderRadius: 8, border: "1px solid var(--border)" }}>
              <p style={{ fontSize: 13, fontWeight: 700, color: "var(--accent-green)", marginBottom: 8 }}>✓ Database (SQLite/Postgres)</p>
              <ul style={{ fontSize: 12, color: "var(--text-secondary)", paddingLeft: 16, lineHeight: 1.8 }}>
                <li>All trades logged</li>
                <li>All signals recorded</li>
                <li>Model snapshots saved</li>
                <li>Runtime state persisted</li>
              </ul>
            </div>
            <div style={{ padding: 16, background: "var(--bg-secondary)", borderRadius: 8, border: "1px solid var(--border)" }}>
              <p style={{ fontSize: 13, fontWeight: 700, color: "var(--accent-blue)", marginBottom: 8 }}>✓ File System</p>
              <ul style={{ fontSize: 12, color: "var(--text-secondary)", paddingLeft: 16, lineHeight: 1.8 }}>
                <li>memory/ patterns JSON</li>
                <li>results/ backtest runs</li>
                <li>live_logs/ bot state</li>
                <li>reports/ summaries</li>
              </ul>
            </div>
            <div style={{ padding: 16, background: "var(--bg-secondary)", borderRadius: 8, border: "1px solid var(--border)" }}>
              <p style={{ fontSize: 13, fontWeight: 700, color: "var(--accent-purple)", marginBottom: 8 }}>✓ Telegram Alerts</p>
              <ul style={{ fontSize: 12, color: "var(--text-secondary)", paddingLeft: 16, lineHeight: 1.8 }}>
                <li>New trade alerts</li>
                <li>Closed trade summary</li>
                <li>FTMO warnings</li>
                <li>Daily/weekly reports</li>
              </ul>
            </div>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
