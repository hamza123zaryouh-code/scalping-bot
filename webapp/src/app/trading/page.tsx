"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge, PnLBadge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { ErrorMessage } from "../../components/ui/Alert";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import type { Trade } from "../../lib/types";

function fmtEur(v: number) {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", minimumFractionDigits: 2 }).format(v);
}

function fmtTime(s: string | null) {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(); } catch { return s; }
}

function SideLabel({ side }: { side: string }) {
  return <Badge variant={side === "buy" ? "green" : "red"}>{side.toUpperCase()}</Badge>;
}

export default function TradingPage() {
  const positionsFetcher = useCallback(() => api.positions(), []);
  const historyFetcher = useCallback(() => api.tradeHistory(200), []);
  const exposureFetcher = useCallback(() => api.exposure(), []);

  const { data: posRes, loading: posLoading, error: posError } = useAutoRefresh(positionsFetcher, 3000);
  const { data: histRes, loading: histLoading } = useAutoRefresh(historyFetcher, 10000);
  const { data: expRes } = useAutoRefresh(exposureFetcher, 5000);

  const pos = (posRes as { data: { positions: unknown[]; count: number; floating_pnl: number; balance: number; equity: number } } | null)?.data;
  const hist = (histRes as { data: { trades: Trade[]; total: number; wins: number; losses: number; total_pnl: number; profit_factor: number; win_rate: number } } | null)?.data;
  const exp = (expRes as { data: { open_trades: number; total_volume: number; total_risk_usd: number; exposure_pct: number; drawdown_pct: number; positions_detail: unknown[] } } | null)?.data;

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Summary stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14 }}>
          {[
            { label: "Open Positions", value: pos?.count ?? 0, color: "#60a5fa" },
            { label: "Floating P&L", value: fmtEur(pos?.floating_pnl ?? 0), color: (pos?.floating_pnl ?? 0) >= 0 ? "var(--accent-green)" : "var(--accent-red)" },
            { label: "Exposure", value: `${(exp?.exposure_pct ?? 0).toFixed(1)}%`, color: (exp?.exposure_pct ?? 0) > 3 ? "var(--accent-yellow)" : "var(--text-primary)" },
            { label: "Win Rate", value: `${hist?.win_rate ?? 0}%`, color: (hist?.win_rate ?? 0) >= 50 ? "var(--accent-green)" : "var(--accent-red)" },
            { label: "Total P&L", value: fmtEur(hist?.total_pnl ?? 0), color: (hist?.total_pnl ?? 0) >= 0 ? "var(--accent-green)" : "var(--accent-red)" },
          ].map((s) => (
            <div key={s.label} className="card">
              <p className="stat-label">{s.label}</p>
              <p style={{ fontSize: 22, fontWeight: 700, color: s.color, marginTop: 6 }}>{s.value}</p>
            </div>
          ))}
        </div>

        {/* Open Positions */}
        <Card title="Open Positions" subtitle={`${pos?.count ?? 0} active trades`}>
          {posLoading ? <PageLoader /> : posError ? <ErrorMessage message={posError} /> : (
            <div style={{ overflowX: "auto" }}>
              <table className="table-dark">
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Volume</th>
                    <th>Entry</th>
                    <th>Current</th>
                    <th>SL</th>
                    <th>TP</th>
                    <th>Profit</th>
                    <th>Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {((exp?.positions_detail ?? []) as Array<{
                    ticket: number | string;
                    symbol: string;
                    side: string;
                    volume: number;
                    entry: number;
                    current: number;
                    sl: number;
                    tp: number;
                    profit: number;
                    duration_min: number;
                  }>).map((p, i) => (
                    <tr key={i}>
                      <td style={{ color: "var(--text-muted)", fontFamily: "monospace" }}>{p.ticket}</td>
                      <td style={{ fontWeight: 600, color: "var(--gold)" }}>{p.symbol}</td>
                      <td><SideLabel side={p.side} /></td>
                      <td>{p.volume?.toFixed(2)}</td>
                      <td style={{ fontFamily: "monospace" }}>{p.entry?.toFixed(2)}</td>
                      <td style={{ fontFamily: "monospace" }}>{p.current?.toFixed(2)}</td>
                      <td style={{ color: "var(--accent-red)", fontFamily: "monospace" }}>{p.sl?.toFixed(2)}</td>
                      <td style={{ color: "var(--accent-green)", fontFamily: "monospace" }}>{p.tp?.toFixed(2)}</td>
                      <td><PnLBadge value={p.profit ?? 0} /></td>
                      <td style={{ color: "var(--text-muted)" }}>{p.duration_min}m</td>
                    </tr>
                  ))}
                  {!exp?.positions_detail?.length && (
                    <tr><td colSpan={10} style={{ textAlign: "center", color: "var(--text-muted)", padding: "30px 0" }}>No open positions</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Trade History */}
        <Card
          title="Trade History"
          subtitle={`${hist?.total ?? 0} closed trades · PF ${hist?.profit_factor ?? 0} · WR ${hist?.win_rate ?? 0}%`}
        >
          {histLoading ? <PageLoader /> : (
            <div style={{ overflowX: "auto" }}>
              <table className="table-dark">
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Signal</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Volume</th>
                    <th>R:R</th>
                    <th>P&L</th>
                    <th>Opened</th>
                    <th>Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {(hist?.trades ?? []).slice(0, 100).map((t, i) => (
                    <tr key={i}>
                      <td style={{ color: "var(--text-muted)", fontFamily: "monospace", fontSize: 11 }}>{t.broker_ticket}</td>
                      <td style={{ fontWeight: 600, color: "var(--gold)" }}>{t.symbol}</td>
                      <td><SideLabel side={t.side} /></td>
                      <td>
                        {t.signal_type ? <Badge variant="blue">{t.signal_type}</Badge> : <span style={{ color: "var(--text-muted)" }}>—</span>}
                      </td>
                      <td style={{ fontFamily: "monospace" }}>{t.entry_price?.toFixed(2)}</td>
                      <td style={{ fontFamily: "monospace" }}>{t.exit_price?.toFixed(2) ?? "—"}</td>
                      <td>{t.volume?.toFixed(2)}</td>
                      <td style={{ color: "var(--text-secondary)" }}>{t.reward_risk_ratio?.toFixed(1) ?? "—"}</td>
                      <td><PnLBadge value={t.pnl ?? 0} /></td>
                      <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{fmtTime(t.opened_at)}</td>
                      <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{fmtTime(t.closed_at)}</td>
                    </tr>
                  ))}
                  {!hist?.trades?.length && (
                    <tr><td colSpan={11} style={{ textAlign: "center", color: "var(--text-muted)", padding: "30px 0" }}>No trade history yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
