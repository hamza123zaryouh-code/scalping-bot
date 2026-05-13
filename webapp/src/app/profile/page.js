'use client'

import { useRouter } from 'next/navigation'
import BackendStatusNotice from '@/components/BackendStatusNotice'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useAuth } from '@/components/AuthSessionProvider'
import { useBotOverview } from '@/lib/useBotOverview'

function formatEur(value) {
  return new Intl.NumberFormat('nl-NL', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(Number(value ?? 0))
}

function SystemRow({ label, value }) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-800 py-3 last:border-0">
      <span className="text-sm text-zinc-500">{label}</span>
      <span className="text-sm font-medium text-white">{value}</span>
    </div>
  )
}

export default function SystemPage() {
  const router = useRouter()
  const { user, signOut } = useAuth()
  const { payload, loading, error } = useBotOverview('Failed to load system page')

  async function handleLogout() {
    await signOut()
    router.replace('/login')
  }

  if (loading) return <LoadingSpinner center />
  if (error) {
    return <div className="rounded-xl border border-red-900 bg-red-950/40 px-5 py-4 text-sm text-red-300">{error}</div>
  }

  const env = payload?.env ?? {}
  const botState = payload?.botState ?? {}
  const metrics = payload?.logAnalysis?.metrics ?? {}
  const latestReport = payload?.logAnalysis?.latestReport?.details?.lines ?? []

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">System View</p>
        <h1 className="mt-2 text-2xl font-bold text-white">System</h1>
        <p className="mt-1 text-sm text-zinc-500">Backend session, bot configuration and local runtime state.</p>
      </div>

      <BackendStatusNotice system={payload?.system} />

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-sm font-semibold text-white">Authenticated Session</h2>
        <div className="mt-4">
          <SystemRow label="User" value={user?.email || 'admin'} />
          <SystemRow label="Role" value={user?.role || 'admin'} />
          <SystemRow label="Mode" value={String(env.mode || 'demo').toUpperCase()} />
          <SystemRow label="Symbol" value={env.symbol || 'XAUUSD'} />
          <SystemRow label="Timeframe" value={env.timeframe || 'M1'} />
        </div>
        <button onClick={handleLogout} className="mt-5 rounded-lg bg-red-950/40 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-950/60">
          Logout
        </button>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-sm font-semibold text-white">Bot Configuration</h2>
        <div className="mt-4">
          <SystemRow label="Check interval" value={`${env.checkIntervalSeconds ?? 0} seconds`} />
          <SystemRow label="History bars" value={String(env.historyBars ?? 0)} />
          <SystemRow label="Risk per trade" value={`${Number(env.riskPerTradePct ?? 0).toFixed(2)}%`} />
          <SystemRow label="Order comment" value={env.orderComment || 'Not set'} />
          <SystemRow label="Trading window" value={`${String(env.sessionStartHour ?? 0).padStart(2, '0')}:00 to ${String(env.sessionEndHour ?? 0).padStart(2, '0')}:00`} />
        </div>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-sm font-semibold text-white">Local Runtime State</h2>
        <div className="mt-4">
          <SystemRow label="Trading day" value={botState.current_trading_day || 'No state'} />
          <SystemRow label="Day-start equity" value={botState.day_start_equity != null ? formatEur(botState.day_start_equity) : 'Unknown'} />
          <SystemRow label="Last processed bar" value={botState.last_processed_bar || 'No bar processed'} />
          <SystemRow label="Last trade time" value={botState.last_trade_time || 'No trade recorded'} />
          <SystemRow label="Last heartbeat" value={botState.last_heartbeat_time || 'No heartbeat recorded'} />
          <SystemRow label="Telegram messages" value={String(botState.telegram_messages_sent ?? 0)} />
        </div>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-sm font-semibold text-white">Live Monitoring Counters</h2>
        <div className="mt-4">
          <SystemRow label="Signal checks without setup" value={String(metrics.noSignalCount ?? 0)} />
          <SystemRow label="Order attempts" value={String(metrics.orderAttemptCount ?? 0)} />
          <SystemRow label="Executed orders" value={String(metrics.executedOrderCount ?? 0)} />
          <SystemRow label="Risk guardrails triggered" value={String(metrics.guardrailCount ?? 0)} />
          <SystemRow label="Heartbeat age" value={metrics.heartbeatAgeMinutes != null ? `${metrics.heartbeatAgeMinutes} minutes` : 'Unknown'} />
        </div>
      </section>

      {latestReport.length > 0 ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Latest Bot Report</h2>
          <div className="mt-4 space-y-2">
            {latestReport.map((line) => (
              <div key={line} className="rounded-lg bg-zinc-950 px-3 py-2 text-xs text-zinc-300">
                {line}
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
