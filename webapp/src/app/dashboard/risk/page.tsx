"use client";
import { useCallback } from "react";
import { AppShell } from "../../../components/layout/AppShell";
import { Card, KPICard } from "../../../components/ui/Card";
import { Badge } from "../../../components/ui/Badge";
import { PageLoader } from "../../../components/ui/Spinner";
import { useAutoRefresh } from "../../../lib/hooks/useAutoRefresh";
import { api } from "../../../lib/api";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface RiskStatus {
  can_trade: boolean;
  equity: number;
  start_capital: number;
  peak_equity: number;
  daily_pnl: number;
  weekly_pnl: number;
  monthly_pnl: number;
  daily_loss_used: number;
  daily_loss_limit: number;
  daily_loss_pct: number;
  daily_remaining: number;
  total_drawdown: number;
  total_drawdown_pct: number;
  total_dd_limit: number;
  trades_today: number;
  max_trades_per_day: number;
  consecutive_losses: number;
  news_lock_until: string | null;
  active_locks: Array<{ lock_type: string; reason: string; severity: string }>;
}

function GaugeBar({
  used, limit, label, color, warn = 0.8,
}: { used: number; limit: number; label: string; color: string; warn?: number }) {
  const pct = limit > 0 ? (used / limit) * 100 : 0;
  const barColor = pct >= warn * 100 ? "#ef4444" : pct >= 60 ? "#f59e0b" : color;
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{label}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: barColor }}>
          €{used.toLocaleString("nl-NL", { minimumFractionDigits: 0 })} / €{limit.toLocaleString("nl-NL")}
          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}> ({pct.toFixed(1)}%)</span>
        </span>
      </div>
      <div style={{ height: 8, background: "var(--border)", borderRadius: 4, overflow: "hidden" }}>
        <div style={{
          width: `${Math.min(pct, 100)}%`, height: "100%",
          background: barColor, borderRadius: 4,
          transition: "width 0.4s ease",
        }} />
      </div>
    </div>
  );
}

export default function RiskDashboardPage() {
  const riskFetcher = useCallback(() => api.riskStatus(), []);
  const ftmoFetcher = useCallback(() => api.ftmoStatus(), []);
  const ddFetcher = useCallback(() => api.drawdownCurve(), []);

  const { data: riskRaw, loading } = useAutoRefresh(riskFetcher, 5000);
  const { data: ftmoRaw } = useAutoRefresh(ftmoFetcher, 10000);
  const { data: ddRaw } = useAutoRefresh(ddFetcher, 30000);

  if (loading) return <AppShell><PageLoader /></AppShell>;

  const risk = (riskRaw as { data: RiskStatus } | null)?.data;
  const ftmo = (ftmoRaw as { data: RiskStatus } | null)?.data;
  const merged: Partial<RiskStatus> = { ...(ftmo ?? {}), ...(risk ?? {}) };

  const ddPoints = (ddRaw as { data: { points: Array<{ date: string; dd: number }> } } | null)?.data?.points ?? [];

  const canTrade = merged.can_trade ?? true;
  const dailyUsed = merged.daily_loss_used ?? 0;
  const dailyLimit = merged.daily_loss_limit ?? 8000;
  const totalDD = merged.total_drawdown ?? 0;
  const totalDDLimit = merged.total_dd_limit ?? 16000;
  const equity = merged.equity ?? 160000;
  const startCapital = merged.start_capital ?? 160000;
  const activeLocks = merged.active_locks ?? [];

  const weeklyLoss = Math.max(0, -(merged.weekly_pnl ?? 0));
  const weeklyLimit = 11200;

  return (
    <AppShell>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)", marginBottom: 4 }}>FTMO Risk Dashboard</h1>
            <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
              Real-time compliance · €160,000 challenge account
            </p>
          </div>
          <div style={{ marginLeft: "auto" }}>
            <div style={{
              padding: "8px 18px", borderRadius: 8,
              background: canTrade ? "#dcfce7" : "#fee2e2",
              border: `1px solid ${canTrade ? "#22c55e" : "#ef4444"}`,
              fontSize: 14, fontWeight: 700,
              color: canTrade ? "#16a34a" : "#dc2626",
            }}>
              {canTrade ? "TRADING ALLOWED" : "TRADING BLOCKED"}
            </div>
          </div>
        </div>

        {/* Active locks */}
        {activeLocks.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {activeLocks.map((lock, i) => (
              <div key={i} style={{
                padding: "10px 14px", borderRadius: 8,
                background: lock.severity === "CRITICAL" ? "#fee2e2" : lock.severity === "BLOCK" ? "#fef3c7" : "#f0fdf4",
                border: `1px solid ${lock.severity === "CRITICAL" ? "#fecaca" : lock.severity === "BLOCK" ? "#fde68a" : "#bbf7d0"}`,
                fontSize: 12.5, color: lock.severity === "CRITICAL" ? "#dc2626" : lock.severity === "BLOCK" ? "#d97706" : "#16a34a",
                fontWeight: 500,
              }}>
                <strong>[{lock.severity}]</strong> {lock.lock_type}: {lock.reason}
              </div>
            ))}
          </div>
        )}

        {/* KPI row */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <Card>
            <KPICard
              label="Daily P&L"
              value={`€${(merged.daily_pnl ?? 0) >= 0 ? "+" : ""}${(merged.daily_pnl ?? 0).toFixed(0)}`}
              trend={(merged.daily_pnl ?? 0) >= 0 ? "up" : "down"}
            />
          </Card>
          <Card>
            <KPICard
              label="Weekly P&L"
              value={`€${(merged.weekly_pnl ?? 0) >= 0 ? "+" : ""}${(merged.weekly_pnl ?? 0).toFixed(0)}`}
              trend={(merged.weekly_pnl ?? 0) >= 0 ? "up" : "down"}
            />
          </Card>
          <Card>
            <KPICard label="Trades Today" value={`${merged.trades_today ?? 0} / ${merged.max_trades_per_day ?? 8}`} />
          </Card>
          <Card>
            <KPICard
              label="Loss Streak"
              value={`${merged.consecutive_losses ?? 0} consecutive`}
              trend={(merged.consecutive_losses ?? 0) === 0 ? "up" : (merged.consecutive_losses ?? 0) >= 3 ? "down" : "neutral"}
            />
          </Card>
        </div>

        {/* FTMO Gauges */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 16 }}>
            FTMO Compliance Limits
          </p>
          <GaugeBar used={dailyUsed} limit={dailyLimit} label="Daily Loss Used" color="#22c55e" warn={0.8} />
          <GaugeBar used={weeklyLoss} limit={weeklyLimit} label="Weekly Loss Used" color="#22c55e" warn={0.8} />
          <GaugeBar used={totalDD} limit={totalDDLimit} label="Total Drawdown" color="#3b82f6" warn={0.75} />
        </Card>

        {/* Equity + drawdown chart */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Drawdown Curve
            </p>
            {ddPoints.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "var(--text-muted)", fontSize: 13 }}>
                No drawdown history yet.
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={ddPoints}>
                  <defs>
                    <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
                  <YAxis tick={{ fontSize: 10, fill: "var(--text-muted)" }} unit="%" />
                  <Tooltip contentStyle={{ background: "var(--bg-secondary)", border: "1px solid var(--border)", fontSize: 11 }} />
                  <ReferenceLine y={5} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: "FTMO 5%", fontSize: 10, fill: "#f59e0b" }} />
                  <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="url(#ddGrad)" dot={false} name="DD %" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </Card>

          <Card>
            <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
              Account Protection Status
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "8px 0" }}>
              {[
                { label: "Account Equity", value: `€${equity.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}`, ok: true },
                { label: "Start Capital", value: `€${startCapital.toLocaleString("nl-NL")}`, ok: true },
                { label: "Peak Equity", value: `€${(merged.peak_equity ?? startCapital).toLocaleString("nl-NL", { minimumFractionDigits: 2 })}`, ok: true },
                { label: "Daily Remaining", value: `€${(merged.daily_remaining ?? dailyLimit).toLocaleString("nl-NL", { minimumFractionDigits: 2 })}`, ok: (merged.daily_remaining ?? dailyLimit) > dailyLimit * 0.2 },
                { label: "News Lock", value: merged.news_lock_until ? `Until ${new Date(merged.news_lock_until).toLocaleTimeString()}` : "None", ok: !merged.news_lock_until },
              ].map((row) => (
                <div key={row.label} style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", borderRadius: 6, background: "var(--bg-secondary)",
                }}>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{row.label}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: row.ok ? "var(--text-primary)" : "#ef4444" }}>
                    {row.value}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* FTMO Rules Reference */}
        <Card>
          <p style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 12 }}>
            FTMO Phase 2 Rules
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
            {[
              { rule: "Daily Loss Limit", val: "€8,000 (5%)", color: "#ef4444" },
              { rule: "Max Loss (Total)", val: "€16,000 (10%)", color: "#ef4444" },
              { rule: "Profit Target", val: "€16,000 (10%)", color: "#22c55e" },
              { rule: "Min Trading Days", val: "≥4 days/month", color: "#3b82f6" },
              { rule: "Max Trades/Day", val: "8 (internal limit)", color: "#f59e0b" },
              { rule: "News Blackout", val: "30min before/20min after", color: "#8b5cf6" },
            ].map((r) => (
              <div key={r.rule} style={{
                padding: "10px 12px", borderRadius: 7,
                background: "var(--bg-secondary)", border: "1px solid var(--border)",
              }}>
                <div style={{ fontSize: 10, color: r.color, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em" }}>{r.rule}</div>
                <div style={{ fontSize: 12, color: "var(--text-primary)", fontWeight: 600, marginTop: 2 }}>{r.val}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
