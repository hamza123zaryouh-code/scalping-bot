'use client'

import { useMemo } from 'react'
import BackendStatusNotice from '@/components/BackendStatusNotice'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useBotOverview } from '@/lib/useBotOverview'

function formatEur(value) {
  return new Intl.NumberFormat('nl-NL', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(Number(value ?? 0))
}

function StatItem({ label, value, className = 'text-white' }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${className}`}>{value}</p>
    </div>
  )
}

export default function AnalyticsPage() {
  const { payload, loading, error } = useBotOverview('Failed to load analytics')

  const summary = useMemo(() => {
    const risk = payload?.risk?.data ?? {}
    const ftmo = risk.ftmo_status ?? {}
    const analytics = payload?.analytics?.data ?? {}
    const logAnalysis = payload?.logAnalysis ?? {}
    return {
      risk,
      ftmo,
      analytics,
      logAnalysis,
      logs: payload?.recentLogs ?? [],
      env: payload?.env ?? {},
    }
  }, [payload])

  if (loading) return <LoadingSpinner center />
  if (error) {
    return <div className="rounded-xl border border-red-900 bg-red-950/40 px-5 py-4 text-sm text-red-300">{error}</div>
  }

  const hasAnalytics =
    Number(summary.analytics.closed_trades ?? 0) > 0 ||
    (summary.analytics.monthly?.length ?? 0) > 0
  const metrics = summary.logAnalysis.metrics ?? {}
  const latestReportLines = summary.logAnalysis.latestReport?.details?.lines ?? []

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">Performance Review</p>
        <h1 className="mt-2 text-2xl font-bold text-white">Analytics</h1>
        <p className="mt-1 text-sm text-zinc-500">Operational analytics for the bot and readiness state for realized trade data.</p>
      </div>

      <BackendStatusNotice system={payload?.system} />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatItem label="Daily Buffer" value={`${Number(summary.ftmo.daily_buffer_pct ?? 0).toFixed(1)}%`} />
        <StatItem label="Total Buffer" value={`${Number(summary.ftmo.total_buffer_pct ?? 0).toFixed(1)}%`} />
        <StatItem label="Fail Probability" value={`${(Number(summary.risk.fail_probability ?? 0) * 100).toFixed(1)}%`} className={Number(summary.risk.fail_probability ?? 0) > 0.25 ? 'text-red-400' : 'text-emerald-400'} />
        <StatItem label="Heartbeat Window" value={`${summary.env.heartbeatMinutes ?? 0} min`} />
      </div>

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatItem label="Checks Without Signal" value={String(metrics.noSignalCount ?? 0)} />
        <StatItem label="Order Attempts" value={String(metrics.orderAttemptCount ?? 0)} />
        <StatItem label="Executed Orders" value={String(metrics.executedOrderCount ?? 0)} className="text-emerald-400" />
        <StatItem label="Reports Logged" value={String(metrics.reportCount ?? 0)} />
      </div>

      {hasAnalytics ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Realized Trade Analytics</h2>
          <div className="mt-4 grid grid-cols-2 gap-4 xl:grid-cols-5">
            <StatItem label="Closed Trades" value={String(summary.analytics.closed_trades ?? 0)} />
            <StatItem label="Win Rate" value={`${(Number(summary.analytics.win_rate ?? 0) * 100).toFixed(1)}%`} />
            <StatItem label="Profit Factor" value={Number(summary.analytics.profit_factor ?? 0).toFixed(2)} />
            <StatItem label="Net PnL" value={formatEur(summary.analytics.total_pnl ?? 0)} className={Number(summary.analytics.total_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'} />
            <StatItem label="Max Drawdown" value={formatEur(summary.analytics.max_drawdown ?? 0)} className="text-amber-400" />
          </div>
        </section>
      ) : null}

      {!hasAnalytics ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Realized Trade Analytics</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-400">
            The backend is connected, but it does not currently expose realized monthly trade analytics. The interface stays active and shows
            runtime health until closed-trade data is available through the API.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-zinc-950 p-4">
              <p className="text-xs uppercase tracking-wider text-zinc-500">Current mode</p>
              <p className="mt-2 text-lg font-semibold text-white">{String(summary.env.mode || 'demo').toUpperCase()}</p>
            </div>
            <div className="rounded-lg bg-zinc-950 p-4">
              <p className="text-xs uppercase tracking-wider text-zinc-500">Last log event</p>
              <p className="mt-2 text-sm leading-6 text-zinc-300">{summary.logs.at(-1) || 'No log event available.'}</p>
            </div>
          </div>
        </section>
      ) : null}

      {latestReportLines.length > 0 ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Latest 2-Hour Report</h2>
          <div className="mt-4 space-y-2">
            {latestReportLines.map((line) => (
              <div key={line} className="rounded-lg bg-zinc-950 px-3 py-2 text-xs text-zinc-300">
                {line}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-sm font-semibold text-white">Runtime Notes</h2>
        <div className="mt-4 space-y-2">
          {(summary.logs.length ? summary.logs : ['No local bot log found.']).map((line) => (
            <div key={line} className="rounded-lg bg-zinc-950 px-3 py-2 text-xs text-zinc-400">
              {line}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
