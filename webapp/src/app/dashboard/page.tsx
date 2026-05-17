"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card, KPICard } from "../../components/ui/Card";
import { Badge, PnLBadge } from "../../components/ui/Badge";
import { PageLoader } from "../../components/ui/Spinner";
import { ErrorMessage } from "../../components/ui/Alert";
import { EquityChart } from "../../components/charts/EquityChart";
import { DrawdownChart } from "../../components/charts/DrawdownChart";
import { MonthlyPnLChart } from "../../components/charts/MonthlyPnLChart";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import type { DashboardData, EquityPoint, DrawdownPoint, MonthlyPnL } from "../../lib/types";

function fmtEur(v: number) {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", minimumFractionDigits: 2 }).format(v);
}

function ProgressBar({ pct, color }: { pct: number; color: string }) {
  const capped = Math.min(pct, 100);
  return (
    <div className="progress-bar" style={{ marginTop: 6 }}>
      <div className="progress-fill" style={{ width: `${capped}%`, background: color }} />
    </div>
  );
}

const STARTING_CAPITAL = 160_000;

export default function DashboardPage() {
  const dashFetcher = useCallback(() => api.dashboard(), []);
  const equityFetcher = useCallback(() => api.equityCurve(), []);
  const ddFetcher = useCallback(() => api.drawdownCurve(), []);
  const monthlyFetcher = useCallback(() => api.monthlyPnL(), []);
  const signalsFetcher = useCallback(() => api.signalsToday(), []);

  const { data: dash, loading: dashLoading, error: dashError } = useAutoRefresh(dashFetcher, 5000);
  const { data: equityRes } = useAutoRefresh(equityFetcher, 30000);
  const { data: ddRes } = useAutoRefresh(ddFetcher, 30000);
  const { data: monthlyRes } = useAutoRefresh(monthlyFetcher, 60000);
  const { data: signalsRes } = useAutoRefresh(signalsFetcher, 10000);

  if (dashLoading) return <AppShell><PageLoader /></AppShell>;
  if (dashError) return <AppShell><ErrorMessage message={dashError} /></AppShell>;

  const d = (dash as { data: DashboardData } | null)?.data;
  const equityPoints: EquityPoint[] = (equityRes as { data: { points: EquityPoint[] } } | null)?.data?.points ?? [];
  const ddPoints: DrawdownPoint[] = (ddRes as { data: { points: DrawdownPoint[] } } | null)?.data?.points ?? [];
  const months: MonthlyPnL[] = (monthlyRes as { data: { months: MonthlyPnL[] } } | null)?.data?.months ?? [];
  const signals = (signalsRes as { data: { signals: unknown[]; count: number; buy_count: number; sell_count: number } } | null)?.data;

  if (!d) return <AppShell><PageLoader /></AppShell>;

  const acc = d.account;
  const perf = d.performance;
  const risk = d.risk;
  const act = d.activity;

  return (
    <AppShell mode={d.mode} lastUpdate={d.timestamp}>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* FTMO Warning */}
        {!risk.can_trade && (
          <div style={{
            background: "rgba(245,158,11,0.08)",
            border: "1px solid rgba(245,158,11,0.25)",
            borderRadius: 10,
            padding: "14px 18px",
            display: "flex",
            alignItems: "center",
            gap: 12,
            color: "#fbbf24",
            fontWeight: 600,
            fontSize: 14,
          }}>
            <span style={{ fontSize: 20 }}>⚠</span>
            FTMO RISK LIMIT REACHED — Trading is disabled. Daily or total loss limit exceeded.
          </div>
        )}

        {/* KPI Grid — Row 1 */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <KPICard
            label="Account Balance"
            value={fmtEur(acc.balance)}
            sub={`Starting capital ${fmtEur(STARTING_CAPITAL)}`}
            color="default"
            icon="💰"
          />
          <KPICard
            label="Equity"
            value={fmtEur(acc.equity)}
            sub={`Floating ${acc.floating_pnl >= 0 ? "+" : ""}${fmtEur(acc.floating_pnl)}`}
            color={acc.floating_pnl > 0 ? "green" : acc.floating_pnl < 0 ? "red" : "default"}
            icon="📈"
          />
          <KPICard
            label="Daily P&L"
            value={fmtEur(acc.daily_pnl)}
            sub={`vs daily limit ${fmtEur(risk.daily_loss_limit)}`}
            color={acc.daily_pnl > 0 ? "green" : acc.daily_pnl < 0 ? "red" : "default"}
            trend={acc.daily_pnl > 0 ? "up" : acc.daily_pnl < 0 ? "down" : "neutral"}
            icon="📊"
          />
          <KPICard
            label="Drawdown"
            value={`${acc.drawdown_pct.toFixed(2)}%`}
            sub={`${fmtEur(acc.drawdown_usd)} / Max 10%`}
            color={acc.drawdown_pct > 4 ? "red" : acc.drawdown_pct > 2 ? "yellow" : acc.drawdown_pct > 0 ? "blue" : "default"}
            icon="📉"
          />
        </div>

        {/* KPI Grid — Row 2 */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <KPICard
            label="Win Rate"
            value={`${perf.win_rate}%`}
            sub={`${perf.wins}W / ${perf.losses}L`}
            color={perf.total_trades === 0 ? "default" : perf.win_rate >= 50 ? "green" : "red"}
            icon="🎯"
          />
          <KPICard
            label="Profit Factor"
            value={perf.profit_factor.toFixed(2)}
            sub={`Target > 1.4`}
            color={perf.total_trades === 0 ? "default" : perf.profit_factor >= 1.4 ? "green" : perf.profit_factor >= 1.0 ? "yellow" : "red"}
            icon="⚖️"
          />
          <KPICard
            label="Total Trades"
            value={perf.total_trades}
            sub={`Total P&L ${fmtEur(perf.total_pnl)}`}
            color={perf.total_trades === 0 ? "default" : perf.total_pnl >= 0 ? "green" : "red"}
            icon="📋"
          />
          <KPICard
            label="AI Confidence"
            value={`${(act.ai_confidence * 100).toFixed(0)}%`}
            sub={`${act.signals_today} signals today`}
            color={act.signals_today === 0 ? "default" : act.ai_confidence >= 0.7 ? "green" : act.ai_confidence >= 0.4 ? "yellow" : "red"}
            icon="🤖"
          />
        </div>

        {/* Charts Row */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
          <Card title="Equity Curve" subtitle={`Starting capital ${fmtEur(STARTING_CAPITAL)}`}>
            <EquityChart data={equityPoints} startingCapital={STARTING_CAPITAL} height={230} />
          </Card>

          <Card title="Drawdown" subtitle="FTMO Max 10% totaal / 5% dag">
            <DrawdownChart data={ddPoints} height={230} maxAllowed={-10} />
          </Card>
        </div>

        {/* Bottom Row */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          {/* Monthly P&L */}
          <Card title="Monthly P&L" style={{ gridColumn: "span 1" }}>
            <MonthlyPnLChart data={months} height={180} />
          </Card>

          {/* FTMO Risk Gauges */}
          <Card title="FTMO Risk Control" subtitle="Phase 2 limits">
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Daily Loss</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: risk.daily_loss_pct > 75 ? "var(--accent-red)" : risk.daily_loss_pct > 0 ? "var(--text-primary)" : "var(--text-secondary)" }}>
                    {fmtEur(risk.daily_loss_used)} / {fmtEur(risk.daily_loss_limit)}
                  </span>
                </div>
                <ProgressBar
                  pct={risk.daily_loss_pct}
                  color={risk.daily_loss_pct > 75 ? "var(--accent-red)" : risk.daily_loss_pct > 50 ? "var(--accent-yellow)" : risk.daily_loss_pct > 0 ? "var(--accent-blue)" : "var(--border)"}
                />
                <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>{risk.daily_loss_pct.toFixed(1)}% used</p>
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Total Drawdown</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: risk.total_loss_pct > 75 ? "var(--accent-red)" : risk.total_loss_pct > 0 ? "var(--text-primary)" : "var(--text-secondary)" }}>
                    {fmtEur(risk.total_loss_used)} / {fmtEur(risk.total_loss_limit)}
                  </span>
                </div>
                <ProgressBar
                  pct={risk.total_loss_pct}
                  color={risk.total_loss_pct > 75 ? "var(--accent-red)" : risk.total_loss_pct > 50 ? "var(--accent-yellow)" : risk.total_loss_pct > 0 ? "var(--accent-blue)" : "var(--border)"}
                />
                <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 3 }}>{risk.total_loss_pct.toFixed(1)}% used</p>
              </div>

              <div style={{ paddingTop: 8, borderTop: "1px solid var(--border)" }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Trading Status</span>
                  <Badge variant={risk.can_trade ? "green" : "red"}>
                    {risk.can_trade ? "ALLOWED" : "BLOCKED"}
                  </Badge>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Open Positions</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{act.open_positions}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Bot Cycles</span>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{act.bot_cycles.toLocaleString()}</span>
                </div>
              </div>
            </div>
          </Card>

          {/* Today's Signals */}
          <Card title="Signals Today" subtitle={`${signals?.count ?? 0} total`}>
            <div style={{ display: "flex", gap: 20, marginBottom: 16 }}>
              <div style={{ textAlign: "center" }}>
                <p style={{ fontSize: 28, fontWeight: 700, color: "var(--accent-green)" }}>{signals?.buy_count ?? 0}</p>
                <p style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Buy</p>
              </div>
              <div style={{ textAlign: "center" }}>
                <p style={{ fontSize: 28, fontWeight: 700, color: (signals?.sell_count ?? 0) > 0 ? "var(--accent-red)" : "var(--text-secondary)" }}>{signals?.sell_count ?? 0}</p>
                <p style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Sell</p>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 120, overflowY: "auto" }}>
              {((signals as { signals: Array<{ time: string; side: string; label?: string; reason?: string }> } | null)?.signals ?? []).slice(-5).reverse().map((s) => (
                <div key={`${s.time}-${s.side}`} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "5px 0", borderBottom: "1px solid var(--border-subtle)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Badge variant={s.side === "buy" ? "green" : "red"}>{s.side.toUpperCase()}</Badge>
                    <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>{s.label ?? s.reason ?? "Signal"}</span>
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                    {new Date(s.time).toLocaleTimeString()}
                  </span>
                </div>
              ))}
              {(signals?.count ?? 0) === 0 && (
                <p style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", padding: "20px 0" }}>No signals yet today</p>
              )}
            </div>

            <div style={{ paddingTop: 12, borderTop: "1px solid var(--border)", marginTop: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Last Signal</span>
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  {act.last_signal ? new Date(act.last_signal).toLocaleTimeString() : "—"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>AI Confidence</span>
                <span style={{ fontSize: 12, fontWeight: 600, color: act.signals_today === 0 ? "var(--text-secondary)" : act.ai_confidence >= 0.7 ? "var(--accent-green)" : "var(--accent-yellow)" }}>
                  {(act.ai_confidence * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
