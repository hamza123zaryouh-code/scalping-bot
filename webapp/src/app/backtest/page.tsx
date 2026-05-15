"use client";
import { useCallback, useMemo, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { WeeklyPerformanceChart } from "../../components/charts/WeeklyPerformanceChart";
import { Card } from "../../components/ui/Card";
import { ErrorMessage } from "../../components/ui/Alert";
import { PageLoader } from "../../components/ui/Spinner";
import { api } from "../../lib/api";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import type { BacktestHistoryItem, BacktestRunResult, WeeklyBacktestSummary } from "../../lib/types";

function formatEur(value: number) {
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function defaultBacktestPayload() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(end.getDate() - 120);

  const fmt = (date: Date) => date.toISOString().slice(0, 10);
  return {
    start_date: fmt(start),
    end_date: fmt(end),
    starting_capital: 160000,
    risk_per_trade: 0.0025,
    sl_atr_multiplier: 1.5,
    tp_atr_multiplier: 3.0,
    max_open_trades: 3,
    commission: 0.35,
    spread_cost: 0.25,
    symbol: "XAUUSD",
  };
}

export default function BacktestPage() {
  const latestFetcher = useCallback(() => api.latestBacktest(), []);
  const historyFetcher = useCallback(() => api.backtestHistory(), []);

  const {
    data: latestRes,
    loading: latestLoading,
    error: latestError,
    refetch: refetchLatest,
  } = useAutoRefresh(latestFetcher, 60000);
  const {
    data: historyRes,
    loading: historyLoading,
    error: historyError,
    refetch: refetchHistory,
  } = useAutoRefresh(historyFetcher, 60000);

  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const latest = (latestRes as { data: BacktestRunResult } | null)?.data ?? null;
  const history = (historyRes as { data: BacktestHistoryItem[] } | null)?.data ?? [];
  const weekly: WeeklyBacktestSummary[] = useMemo(() => latest?.weekly_summary ?? [], [latest]);

  const bestWeek = useMemo(
    () => weekly.reduce<WeeklyBacktestSummary | null>((best, row) => (!best || row.pnl > best.pnl ? row : best), null),
    [weekly],
  );
  const worstWeek = useMemo(
    () => weekly.reduce<WeeklyBacktestSummary | null>((worst, row) => (!worst || row.pnl < worst.pnl ? row : worst), null),
    [weekly],
  );

  async function runBacktestAgain() {
    try {
      setRunning(true);
      setRunError(null);
      await api.runBacktest(defaultBacktestPayload());
      await Promise.all([refetchLatest(), refetchHistory()]);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Backtest mislukt");
    } finally {
      setRunning(false);
    }
  }

  const noLatestYet = latestError?.includes("Nog geen backtest resultaat beschikbaar");

  return (
    <AppShell>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <Card
          title="Backtest Control"
          subtitle="Run een nieuwe XAUUSD backtest en bekijk de weekresultaten in euro en procent"
          action={(
            <button
              type="button"
              onClick={runBacktestAgain}
              disabled={running}
              style={{
                border: "1px solid var(--accent-blue)",
                background: running ? "rgba(59,130,246,0.12)" : "rgba(59,130,246,0.18)",
                color: "var(--accent-blue)",
                borderRadius: 10,
                padding: "10px 14px",
                fontSize: 12,
                fontWeight: 700,
                cursor: running ? "wait" : "pointer",
              }}
            >
              {running ? "Backtest draait..." : "Run Backtest Opnieuw"}
            </button>
          )}
        >
          <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.7 }}>
            Standaard wordt de laatste 120 dagen op <strong>XAUUSD</strong> getest met startkapitaal van{" "}
            <strong>{formatEur(160000)}</strong>.
          </p>
          {runError ? <div style={{ marginTop: 12 }}><ErrorMessage message={runError} /></div> : null}
        </Card>

        {latestLoading && !latest ? <PageLoader /> : null}
        {!latestLoading && latestError && !noLatestYet ? <ErrorMessage message={latestError} /> : null}
        {noLatestYet ? (
          <Card title="Nog Geen Backtest">
            <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
              Er is nog geen opgeslagen backtestresultaat. Start hierboven een nieuwe run en de weekgrafiek verschijnt hier automatisch.
            </p>
          </Card>
        ) : null}

        {latest ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
              {[
                { label: "Total Return", value: formatPct(latest.metrics.total_return_pct), color: latest.metrics.total_return_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)" },
                { label: "Profit Factor", value: latest.metrics.profit_factor.toFixed(2), color: "var(--accent-blue)" },
                { label: "Win Rate", value: formatPct(latest.metrics.win_rate * 100), color: latest.metrics.win_rate >= 0.5 ? "var(--accent-green)" : "var(--accent-yellow)" },
                { label: "Max Drawdown", value: `${latest.metrics.max_drawdown_pct.toFixed(2)}%`, color: "var(--accent-red)" },
                { label: "Weeks", value: String(weekly.length), color: "var(--text-primary)" },
                { label: "Trades", value: String(latest.metrics.total_trades), color: "var(--text-primary)" },
                { label: "Best Week", value: bestWeek ? formatEur(bestWeek.pnl) : "—", color: "var(--accent-green)" },
                { label: "Worst Week", value: worstWeek ? formatEur(worstWeek.pnl) : "—", color: "var(--accent-red)" },
              ].map((item) => (
                <div key={item.label} className="card">
                  <p className="stat-label">{item.label}</p>
                  <p style={{ fontSize: 22, fontWeight: 700, color: item.color, marginTop: 6 }}>{item.value}</p>
                </div>
              ))}
            </div>

            <Card title="Weekly Backtest Result" subtitle="Per week in euro en procent">
              <WeeklyPerformanceChart data={weekly} height={320} />
            </Card>

            <Card title="Weekly Breakdown" subtitle="Iedere week met PnL, return en equity">
              <div style={{ overflowX: "auto" }}>
                <table className="table-dark">
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Week Start</th>
                      <th>Trades</th>
                      <th>PnL EUR</th>
                      <th>Return %</th>
                      <th>Start Equity</th>
                      <th>End Equity</th>
                      <th>Win Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {weekly.map((row) => (
                      <tr key={row.week}>
                        <td style={{ fontWeight: 700, color: "var(--text-primary)" }}>{row.week}</td>
                        <td style={{ color: "var(--text-secondary)" }}>{row.week_start}</td>
                        <td>{row.trades}</td>
                        <td style={{ color: row.pnl >= 0 ? "var(--accent-green)" : "var(--accent-red)", fontWeight: 700 }}>
                          {row.pnl >= 0 ? "+" : ""}{formatEur(row.pnl)}
                        </td>
                        <td style={{ color: row.return_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                          {formatPct(row.return_pct)}
                        </td>
                        <td>{formatEur(row.start_equity)}</td>
                        <td>{formatEur(row.end_equity)}</td>
                        <td>{(row.win_rate * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                    {!weekly.length ? (
                      <tr>
                        <td colSpan={8} style={{ textAlign: "center", color: "var(--text-muted)", padding: "36px 0" }}>
                          Geen weekresultaten beschikbaar
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        ) : null}

        <Card title="Recent Backtest Runs" subtitle="Laatste runs uit de actieve backend sessie">
          {historyLoading ? <PageLoader /> : historyError ? <ErrorMessage message={historyError} /> : (
            <div style={{ overflowX: "auto" }}>
              <table className="table-dark">
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Period</th>
                    <th>Trades</th>
                    <th>Win Rate</th>
                    <th>Profit Factor</th>
                    <th>Return</th>
                    <th>Drawdown</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row) => (
                    <tr key={String(row.task_id ?? row.created ?? Math.random())}>
                      <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--text-muted)" }}>{String(row.task_id ?? "—").slice(0, 12)}</td>
                      <td>{row.start_date} → {row.end_date}</td>
                      <td>{row.total_trades ?? "—"}</td>
                      <td>{typeof row.win_rate === "number" ? `${(row.win_rate * 100).toFixed(1)}%` : "—"}</td>
                      <td>{typeof row.profit_factor === "number" ? row.profit_factor.toFixed(2) : "—"}</td>
                      <td style={{ color: Number(row.total_return_pct) >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                        {typeof row.total_return_pct === "number" ? formatPct(row.total_return_pct) : "—"}
                      </td>
                      <td>{typeof row.max_drawdown_pct === "number" ? `${row.max_drawdown_pct.toFixed(2)}%` : "—"}</td>
                      <td style={{ color: "var(--text-secondary)" }}>
                        {row.created_at ? new Date(String(row.created_at)).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                  {!history.length ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", color: "var(--text-muted)", padding: "36px 0" }}>
                        Nog geen recente runs in deze backend sessie
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
