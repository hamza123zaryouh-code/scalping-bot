"use client";
import { useCallback, useEffect, useState } from "react";
import { AppShell } from "../../../components/layout/AppShell";
import { Card, KPICard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { PageLoader } from "../../../components/ui/Spinner";
import { useAutoRefresh } from "../../../lib/hooks/useAutoRefresh";
import { api } from "../../../lib/api";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";

interface AuditRecord {
  ts: string;
  event: string;
  ticket: string;
  symbol: string;
  side: string;
  requested_price: number;
  fill_price: number;
  slippage_points: number;
  spread_points: number;
  volume: number;
  latency_ms: number;
  retcode: number | null;
  attempt: number;
  broker_error: string | null;
}

function EventBadge({ event }: { event: string }) {
  const map: Record<string, string> = {
    order_filled: "success",
    slippage_alert: "warning",
    order_rejected: "danger",
    order_retried: "warning",
    close_filled: "success",
    close_rejected: "danger",
    kill_switch: "danger",
  };
  return <Badge variant={(map[event] as "success" | "warning" | "danger" | "info" | "neutral") ?? "neutral"}>{event.replace(/_/g, " ")}</Badge>;
}

export default function ExecutionPage() {
  const histFetcher = useCallback(() => api.tradeHistory(50), []);
  const { data: raw, loading } = useAutoRefresh(histFetcher, 30000);

  if (loading) return <AppShell><PageLoader /></AppShell>;

  const trades = (raw as { data: { trades: AuditRecord[] } } | null)?.data?.trades ?? [];

  // Derive execution metrics from trade history (use slippage/latency if available)
  const filled = trades.filter((t: AuditRecord) => t.event === "order_filled" || t.event === "close_filled");
  const rejected = trades.filter((t: AuditRecord) => t.event === "order_rejected" || t.event === "close_rejected");
  const slippageAlerts = trades.filter((t: AuditRecord) => t.event === "slippage_alert");

  const avgSlippage = filled.length > 0
    ? filled.reduce((s: number, t: AuditRecord) => s + (t.slippage_points ?? 0), 0) / filled.length
    : 0;

  const avgLatency = filled.length > 0
    ? filled.reduce((s: number, t: AuditRecord) => s + (t.latency_ms ?? 0), 0) / filled.length
    : 0;

  const avgSpread = filled.length > 0
    ? filled.reduce((s: number, t: AuditRecord) => s + (t.spread_points ?? 0), 0) / filled.length
    : 0;

  const slippageHistory = filled.slice(-30).map((t: AuditRecord, i: number) => ({
    n: i + 1,
    slippage: t.slippage_points ?? 0,
    spread: t.spread_points ?? 0,
    latency: Math.round(t.latency_ms ?? 0),
    ts: t.ts ? new Date(t.ts).toLocaleTimeString() : `#${i + 1}`,
  }));

  const latencyBuckets = [
    { range: "0–50ms", count: filled.filter((t: AuditRecord) => (t.latency_ms ?? 0) < 50).length },
    { range: "50–100ms", count: filled.filter((t: AuditRecord) => (t.latency_ms ?? 0) >= 50 && (t.latency_ms ?? 0) < 100).length },
    { range: "100–200ms", count: filled.filter((t: AuditRecord) => (t.latency_ms ?? 0) >= 100 && (t.latency_ms ?? 0) < 200).length },
    { range: "200–500ms", count: filled.filter((t: AuditRecord) => (t.latency_ms ?? 0) >= 200 && (t.latency_ms ?? 0) < 500).length },
    { range: ">500ms", count: filled.filter((t: AuditRecord) => (t.latency_ms ?? 0) >= 500).length },
  ];

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>Execution Dashboard</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            MT5 order execution quality · {filled.length} fills analyzed
          </p>
        </div>

        {/* KPI row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <Card>
            <KPICard
              label="Avg Slippage"
              value={`${avgSlippage.toFixed(1)} pts`}
              trend={avgSlippage < 5 ? "up" : avgSlippage < 15 ? "neutral" : "down"}
            />
          </Card>
          <Card>
            <KPICard label="Avg Latency" value={`${Math.round(avgLatency)}ms`} />
          </Card>
          <Card>
            <KPICard label="Avg Spread" value={`${avgSpread.toFixed(1)} pts`} />
          </Card>
          <Card>
            <KPICard
              label="Rejection Rate"
              value={trades.length > 0 ? `${((rejected.length / trades.length) * 100).toFixed(1)}%` : "0%"}
              trend={rejected.length === 0 ? "up" : "down"}
            />
          </Card>
        </div>

        {/* Slippage + Latency charts */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Slippage History (last 30 fills)
            </p>
            {slippageHistory.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>No execution data yet.</div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={slippageHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="n" tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                  <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                  <ReferenceLine y={20} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: "Alert", fontSize: 10, fill: "#f59e0b" }} />
                  <Bar dataKey="slippage" name="Slippage (pts)" radius={[3, 3, 0, 0]}>
                    {slippageHistory.map((entry, i) => (
                      <Cell key={i} fill={entry.slippage > 20 ? "#ef4444" : entry.slippage > 10 ? "#f59e0b" : "#22c55e"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>

          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Execution Latency Distribution
            </p>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={latencyBuckets} margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="range" tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                <Bar dataKey="count" name="Orders" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>

        {/* Spread history */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            Spread at Execution (last 30 fills)
          </p>
          {slippageHistory.length === 0 ? (
            <div style={{ textAlign: "center", padding: "24px 0", color: "var(--text-muted)", fontSize: 13 }}>No data.</div>
          ) : (
            <ResponsiveContainer width="100%" height={130}>
              <LineChart data={slippageHistory}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="n" tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                <ReferenceLine y={50} stroke="#ef4444" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="spread" stroke="#8b5cf6" strokeWidth={2} dot={false} name="Spread (pts)" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Recent execution log */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            Recent Execution Events
          </p>
          {trades.length === 0 ? (
            <div style={{ textAlign: "center", padding: "30px 0", color: "var(--text-muted)", fontSize: 13 }}>
              Execution audit log is empty. Events appear when trades are placed via MT5.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
                    {["Time", "Event", "Side", "Req Price", "Fill Price", "Slippage", "Spread", "Latency", "Attempt"].map((h) => (
                      <th key={h} style={{ padding: "6px 10px", borderBottom: "1px solid var(--border)", fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 20).map((t: AuditRecord, i: number) => (
                    <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                      <td style={{ padding: "7px 10px", color: "var(--text-muted)", fontSize: 11 }}>
                        {t.ts ? new Date(t.ts).toLocaleTimeString() : "—"}
                      </td>
                      <td style={{ padding: "7px 10px" }}><EventBadge event={t.event} /></td>
                      <td style={{ padding: "7px 10px" }}>
                        <Badge variant={t.side === "buy" ? "success" : "danger"}>{(t.side ?? "—").toUpperCase()}</Badge>
                      </td>
                      <td style={{ padding: "7px 10px" }}>{t.requested_price ? t.requested_price.toFixed(2) : "—"}</td>
                      <td style={{ padding: "7px 10px" }}>{t.fill_price ? t.fill_price.toFixed(2) : "—"}</td>
                      <td style={{ padding: "7px 10px", color: (t.slippage_points ?? 0) > 20 ? "#ef4444" : "var(--text-primary)" }}>
                        {(t.slippage_points ?? 0).toFixed(1)}
                      </td>
                      <td style={{ padding: "7px 10px" }}>{(t.spread_points ?? 0).toFixed(1)}</td>
                      <td style={{ padding: "7px 10px" }}>{Math.round(t.latency_ms ?? 0)}ms</td>
                      <td style={{ padding: "7px 10px", color: "var(--text-muted)" }}>{t.attempt ?? 1}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
