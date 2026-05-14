"use client";
import { useCallback } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Alert } from "../../components/ui/Alert";
import { PageLoader } from "../../components/ui/Spinner";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { api } from "../../lib/api";
import { DrawdownChart } from "../../components/charts/DrawdownChart";

function fmtEur(v: number) {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", minimumFractionDigits: 2 }).format(v);
}

function GaugeBar({ pct, label, used, limit, warn = 60, danger = 85 }: {
  pct: number; label: string; used: number; limit: number; warn?: number; danger?: number;
}) {
  const color = pct >= danger ? "var(--accent-red)" : pct >= warn ? "var(--accent-yellow)" : "var(--accent-green)";
  const capped = Math.min(pct, 100);
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{label}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color }}>
          {fmtEur(used)} / {fmtEur(limit)} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div style={{ height: 10, background: "var(--border)", borderRadius: 5, overflow: "hidden" }}>
        <div style={{ width: `${capped}%`, height: "100%", background: color, borderRadius: 5, transition: "width 0.5s ease" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>0</span>
        <span style={{ fontSize: 10, color: "var(--accent-yellow)" }}>⚠ {warn}%</span>
        <span style={{ fontSize: 10, color: "var(--accent-red)" }}>🚫 {danger}%</span>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{fmtEur(limit)}</span>
      </div>
    </div>
  );
}

export default function RiskPage() {
  const riskFetcher = useCallback(() => api.riskStatus(), []);
  const dashFetcher = useCallback(() => api.dashboard(), []);
  const ddFetcher = useCallback(() => api.drawdownCurve(), []);

  const { data: riskRes, loading } = useAutoRefresh(riskFetcher, 5000);
  const { data: dashRes } = useAutoRefresh(dashFetcher, 5000);
  const { data: ddRes } = useAutoRefresh(ddFetcher, 30000);

  const risk = (dashRes as { data: { risk: { daily_loss_limit: number; daily_loss_used: number; daily_loss_pct: number; total_loss_limit: number; total_loss_used: number; total_loss_pct: number; can_trade: boolean }; account: { drawdown_pct: number; drawdown_usd: number; balance: number; equity: number }; activity: { open_positions: number } } } | null)?.data;
  const ddPoints = (ddRes as { data: { points: Array<{ time: string; drawdown_pct: number }> } } | null)?.data?.points ?? [];
  const riskDetail = (riskRes as { data: unknown } | null)?.data;

  const r = risk?.risk;
  const acc = risk?.account;

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>

        {/* Status Banner */}
        {r && !r.can_trade && (
          <Alert type="error" title="TRADING BLOCKED — FTMO Limit Reached">
            Daily loss limit or total drawdown limit has been exceeded. No new trades will be opened until limits reset.
          </Alert>
        )}
        {r && r.can_trade && r.daily_loss_pct > 75 && (
          <Alert type="warning" title="Daily Loss Warning">
            You are at {r.daily_loss_pct.toFixed(1)}% of your daily loss limit. Be careful with new entries.
          </Alert>
        )}

        {/* Risk KPIs */}
        {!loading && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
            <div className="card">
              <p className="stat-label">Trading Status</p>
              <p style={{ fontSize: 24, fontWeight: 700, color: r?.can_trade ? "var(--accent-green)" : "var(--accent-red)", marginTop: 6 }}>
                {r?.can_trade ? "ALLOWED" : "BLOCKED"}
              </p>
            </div>
            <div className="card">
              <p className="stat-label">Daily Loss Used</p>
              <p style={{ fontSize: 24, fontWeight: 700, color: (r?.daily_loss_pct ?? 0) > 75 ? "var(--accent-red)" : "var(--accent-green)", marginTop: 6 }}>
                {`${(r?.daily_loss_pct ?? 0).toFixed(1)}%`}
              </p>
            </div>
            <div className="card">
              <p className="stat-label">Total DD Used</p>
              <p style={{ fontSize: 24, fontWeight: 700, color: (r?.total_loss_pct ?? 0) > 75 ? "var(--accent-red)" : "var(--accent-green)", marginTop: 6 }}>
                {`${(r?.total_loss_pct ?? 0).toFixed(1)}%`}
              </p>
            </div>
            <div className="card">
              <p className="stat-label">Drawdown</p>
              <p style={{ fontSize: 24, fontWeight: 700, color: (acc?.drawdown_pct ?? 0) > 4 ? "var(--accent-red)" : "var(--accent-green)", marginTop: 6 }}>
                {`${(acc?.drawdown_pct ?? 0).toFixed(2)}%`}
              </p>
            </div>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* FTMO Limits */}
          <Card title="FTMO Compliance Limits" subtitle="Phase 2 rules — €160,000 account">
            {r ? (
              <div style={{ paddingTop: 8 }}>
                <GaugeBar
                  label="Daily Loss Limit"
                  pct={r.daily_loss_pct}
                  used={r.daily_loss_used}
                  limit={r.daily_loss_limit}
                  warn={60}
                  danger={85}
                />
                <GaugeBar
                  label="Max Total Drawdown"
                  pct={r.total_loss_pct}
                  used={r.total_loss_used}
                  limit={r.total_loss_limit}
                  warn={60}
                  danger={85}
                />
                <div style={{ borderTop: "1px solid var(--border)", paddingTop: 16, marginTop: 4 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    {(["Balance", "Equity", "Open Positions", "DD Amount"] as const).map((lbl) => {
                      const valMap: Record<string, string> = {
                        "Balance": fmtEur(acc?.balance ?? 0),
                        "Equity": fmtEur(acc?.equity ?? 0),
                        "Open Positions": String(risk?.activity?.open_positions ?? 0),
                        "DD Amount": fmtEur(acc?.drawdown_usd ?? 0),
                      };
                      return (
                        <div key={lbl} style={{ padding: "8px 0" }}>
                          <p style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{lbl}</p>
                          <p style={{ fontSize: 15, fontWeight: 600, color: "var(--text-primary)", marginTop: 2 }}>{valMap[lbl]}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : <PageLoader />}
          </Card>

          {/* FTMO Rules */}
          <Card title="FTMO Phase 2 Rules" subtitle="Automated compliance">
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { rule: "Max Daily Loss", limit: "€8,000 (5%)", status: (r?.daily_loss_pct ?? 0) < 85 },
                { rule: "Max Total Drawdown", limit: "€16,000 (10%)", status: (r?.total_loss_pct ?? 0) < 85 },
                { rule: "Min Trading Days", limit: "10 days / 30 days", status: true },
                { rule: "Profit Target", limit: "€8,000 (5%)", status: (acc?.balance ?? 160000) > 168000 },
                { rule: "No Weekend Holds", limit: "Close Friday 22:00", status: true },
                { rule: "Risk Per Trade", limit: "0.3–0.4% max", status: true },
                { rule: "Max Positions", limit: "3 concurrent", status: (risk?.activity?.open_positions ?? 0) <= 3 },
                { rule: "ADX Filter", limit: "Min 22 (trending)", status: true },
              ].map((item, i) => (
                <div key={i} style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "10px 12px",
                  background: "var(--bg-secondary)",
                  borderRadius: 8,
                }}>
                  <div>
                    <p style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>{item.rule}</p>
                    <p style={{ fontSize: 11, color: "var(--text-muted)" }}>{item.limit}</p>
                  </div>
                  <Badge variant={item.status ? "green" : "red"}>
                    {item.status ? "✓ OK" : "✕ FAIL"}
                  </Badge>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Drawdown Chart */}
        <Card title="Drawdown History" subtitle="Historical drawdown percentage">
          <DrawdownChart data={ddPoints} height={200} maxAllowed={-6} />
        </Card>

        {/* Risk Service Detail */}
        {!!riskDetail && (
          <Card title="Risk Service Detail">
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
              {JSON.stringify(riskDetail, null, 2).slice(0, 2000)}
            </pre>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
