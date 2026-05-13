'use client'

import Link from 'next/link'
import { useMemo } from 'react'
import BackendStatusNotice from '@/components/BackendStatusNotice'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatDateTime } from '@/lib/utils'
import { useBotOverview } from '@/lib/useBotOverview'

function formatEur(value) {
  return new Intl.NumberFormat('nl-NL', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(Number(value ?? 0))
}

function StatCard({ label, value, note, valueClass = 'text-white' }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">{label}</p>
      <p className={`mt-1 text-2xl font-black leading-none ${valueClass}`}>{value}</p>
      {note ? <p className="mt-2 text-xs text-zinc-600">{note}</p> : null}
    </div>
  )
}

export default function DashboardPage() {
  const { payload, loading, error } = useBotOverview('Failed to load bot overview')

  const derived = useMemo(() => {
    const env = payload?.env ?? {}
    const risk = payload?.risk?.data ?? {}
    const ftmo = risk.ftmo_status ?? {}
    const signal = payload?.signal?.data ?? null
    const positions = payload?.positions?.data ?? []
    const analytics = payload?.analytics?.data ?? {}
    const logMetrics = payload?.logAnalysis?.metrics ?? {}
    return {
      env,
      risk,
      ftmo,
      signal,
      positions,
      analytics,
      logMetrics,
      events: payload?.logAnalysis?.recentEvents ?? [],
      serviceOnline: payload?.health?.status === 'healthy',
    }
  }, [payload])

  if (loading) return <LoadingSpinner center />
  if (error) {
    return <div className="rounded-xl border border-red-900 bg-red-950/40 px-5 py-4 text-sm text-red-300">{error}</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">Overview</p>
          <h1 className="mt-2 text-2xl font-bold text-white">XAUUSD Desk</h1>
        </div>
        <div className="flex gap-2">
          <Link href="/trades" className="rounded-lg border border-zinc-700 px-3.5 py-2 text-sm font-semibold text-zinc-300 hover:bg-zinc-800 hover:text-white">
            Trades
          </Link>
          <Link href="/reviews" className="rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-semibold text-white hover:bg-emerald-500">
            Risk
          </Link>
        </div>
      </div>

      <BackendStatusNotice system={payload?.system} />

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Mode" value={(derived.env.mode || 'demo').toUpperCase()} />
        <StatCard label="Symbol" value={`${derived.env.symbol || 'XAUUSD'} | ${derived.env.timeframe || 'M1'}`} />
        <StatCard label="FTMO" value={(derived.ftmo.risk_level || 'unknown').toUpperCase()} valueClass={derived.ftmo.risk_level === 'red' ? 'text-red-400' : derived.ftmo.risk_level === 'yellow' ? 'text-amber-400' : 'text-emerald-400'} />
        <StatCard label="Service" value={derived.serviceOnline ? 'ONLINE' : 'OFFLINE'} valueClass={derived.serviceOnline ? 'text-emerald-400' : 'text-red-400'} />
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Positions" value={String(derived.positions.length)} />
        <StatCard label="Orders" value={String(derived.logMetrics.executedOrderCount ?? 0)} />
        <StatCard label="Last Signal" value={derived.signal?.entry_label ? `${derived.signal.entry_label} ${String(derived.signal.side || '').toUpperCase()}` : 'NONE'} />
        <StatCard label="Last Bar" value={payload?.botState?.last_processed_bar || 'NONE'} />
      </div>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-white">Live Activity</h2>
          <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-400">
            15s
          </span>
        </div>
        <div className="mt-4 space-y-2">
          {derived.events.length === 0 ? (
            <div className="rounded-lg bg-zinc-950 px-3 py-3 text-sm text-zinc-500">No parsed bot events available yet.</div>
          ) : (
            derived.events.slice(0, 6).map((event) => (
              <div key={`${event.timestamp}-${event.type}-${event.summary}`} className="rounded-lg bg-zinc-950 px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-white">{event.title}</p>
                  <span className="text-xs text-zinc-500">{formatDateTime(event.timestamp)}</span>
                </div>
                <p className="mt-1 text-sm text-zinc-300">{event.summary}</p>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-white">Risk Snapshot</h2>
          <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-400">
            {payload?.botState?.last_heartbeat_time ? formatDateTime(payload.botState.last_heartbeat_time) : 'Unavailable'}
          </span>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-5">
          <StatCard label="Equity" value={formatEur(derived.risk.equity ?? 0)} />
          <StatCard label="Balance" value={formatEur(derived.risk.balance ?? 0)} />
          <StatCard label="Daily Buffer" value={`${Number(derived.ftmo.daily_buffer_pct ?? 0).toFixed(1)}%`} />
          <StatCard label="Total Buffer" value={`${Number(derived.ftmo.total_buffer_pct ?? 0).toFixed(1)}%`} />
          <StatCard label="Stress" value={`${Number(derived.risk.stress_score ?? 0).toFixed(0)} / 100`} />
        </div>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-white">Analytics Snapshot</h2>
          <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs text-zinc-400">
            {derived.analytics.generated_at ? formatDateTime(derived.analytics.generated_at) : 'No dataset'}
          </span>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-5">
          <StatCard label="Closed Trades" value={String(derived.analytics.closed_trades ?? 0)} />
          <StatCard label="Win Rate" value={`${(Number(derived.analytics.win_rate ?? 0) * 100).toFixed(1)}%`} />
          <StatCard label="Profit Factor" value={Number(derived.analytics.profit_factor ?? 0).toFixed(2)} />
          <StatCard label="Net PnL" value={formatEur(derived.analytics.total_pnl ?? 0)} valueClass={Number(derived.analytics.total_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'} />
          <StatCard label="Max Drawdown" value={formatEur(derived.analytics.max_drawdown ?? 0)} valueClass="text-amber-400" />
        </div>
      </section>
    </div>
  )
}
