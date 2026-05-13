'use client'

import { useMemo } from 'react'
import BackendStatusNotice from '@/components/BackendStatusNotice'
import LoadingSpinner from '@/components/LoadingSpinner'
import { formatDateTime } from '@/lib/utils'
import { useBotOverview } from '@/lib/useBotOverview'

function DataTable({ title, rows, columns }) {
  const safeRows = Array.isArray(rows) ? rows : []
  const safeColumns = Array.isArray(columns) ? columns : []

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900">
      <div className="border-b border-zinc-800 px-5 py-4">
        <h2 className="text-sm font-semibold text-zinc-300">{title}</h2>
      </div>
      {safeRows.length === 0 ? (
        <div className="px-5 py-8 text-sm text-zinc-600">No data available.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-zinc-800">
              <tr>
                {safeColumns.map((column) => (
                  <th key={column.key} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-zinc-500">
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800">
              {safeRows.map((row, index) => (
                <tr key={index} className="hover:bg-zinc-800/40">
                  {safeColumns.map((column) => (
                    <td key={column.key} className="px-4 py-3 text-zinc-300">
                      {column.render ? column.render(row) : row[column.key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default function LiveDeskPage() {
  const { payload, loading, error } = useBotOverview('Failed to load live desk')

  const positions = payload?.positions?.data ?? []
  const signal = payload?.signal?.data ?? null
  const botState = payload?.live?.data?.bot_state ?? payload?.botState ?? {}
  const events = payload?.logAnalysis?.recentEvents ?? []
  const metrics = payload?.logAnalysis?.metrics ?? {}

  const positionColumns = useMemo(
    () => [
      { key: 'symbol', label: 'Symbol' },
      { key: 'side', label: 'Side', render: (row) => String(row.side || '').toUpperCase() },
      { key: 'volume', label: 'Volume' },
      { key: 'open_price', label: 'Open', render: (row) => Number(row.open_price ?? 0).toFixed(2) },
      { key: 'current_price', label: 'Current', render: (row) => Number(row.current_price ?? 0).toFixed(2) },
      { key: 'unrealized_pnl', label: 'PnL', render: (row) => <span className={Number(row.unrealized_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}>${Number(row.unrealized_pnl ?? 0).toFixed(2)}</span> },
    ],
    []
  )

  const stateRows = Object.entries(botState).map(([key, value]) => ({
    field: key,
    value: value == null ? '-' : String(value),
  }))

  if (loading) return <LoadingSpinner center />
  if (error) {
    return <div className="rounded-xl border border-red-900 bg-red-950/40 px-5 py-4 text-sm text-red-300">{error}</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">Live Monitoring</p>
        <h1 className="mt-2 text-2xl font-bold text-white">Live Desk</h1>
        <p className="mt-1 text-sm text-zinc-500">Current signal state, open exposure and bot runtime details.</p>
      </div>

      <BackendStatusNotice system={payload?.system} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Signal Watch</h2>
          {!signal ? (
            <p className="mt-3 text-sm text-zinc-500">No qualified signal is active right now.</p>
          ) : (
            <div className="mt-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="rounded-full bg-zinc-800 px-3 py-1 text-xs font-semibold text-zinc-300">
                  {signal.entry_label} | {String(signal.side || '').toUpperCase()}
                </span>
                <span className="text-xs text-zinc-500">{signal.trigger_time}</span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-lg bg-zinc-950 p-3">
                  <p className="text-xs uppercase tracking-widest text-zinc-500">Reference price</p>
                  <p className="mt-1 font-semibold text-white">{Number(signal.reference_price ?? 0).toFixed(2)}</p>
                </div>
                <div className="rounded-lg bg-zinc-950 p-3">
                  <p className="text-xs uppercase tracking-widest text-zinc-500">ATR</p>
                  <p className="mt-1 font-semibold text-white">{Number(signal.atr_value ?? 0).toFixed(2)}</p>
                </div>
              </div>
              <p className="text-sm leading-6 text-zinc-400">{signal.reason || 'No signal rationale supplied.'}</p>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Recent Engine Activity</h2>
          <div className="mt-4 space-y-2">
            {events.length === 0 ? (
              <p className="text-sm text-zinc-500">No local bot events found.</p>
            ) : (
              events.slice(0, 8).map((event) => (
                <div key={`${event.timestamp}-${event.type}-${event.summary}`} className="rounded-lg bg-zinc-950 px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold text-white">{event.title}</p>
                    <span className="text-[11px] text-zinc-500">{formatDateTime(event.timestamp)}</span>
                  </div>
                  <p className="mt-1 text-xs text-zinc-400">{event.summary}</p>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Order attempts</p>
          <p className="mt-1 text-2xl font-bold text-white">{metrics.orderAttemptCount ?? 0}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Executed orders</p>
          <p className="mt-1 text-2xl font-bold text-emerald-400">{metrics.executedOrderCount ?? 0}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Guardrails hit</p>
          <p className="mt-1 text-2xl font-bold text-amber-400">{metrics.guardrailCount ?? 0}</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Heartbeat age</p>
          <p className="mt-1 text-2xl font-bold text-white">
            {metrics.heartbeatAgeMinutes != null ? `${metrics.heartbeatAgeMinutes}m` : '-'}
          </p>
        </div>
      </div>

      <DataTable title="Open Positions" rows={positions} columns={positionColumns} />
      <DataTable title="Bot State" rows={stateRows} columns={[{ key: 'field', label: 'Field' }, { key: 'value', label: 'Value' }]} />
    </div>
  )
}
