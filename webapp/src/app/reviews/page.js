'use client'

import { useEffect, useState } from 'react'
import BackendStatusNotice from '@/components/BackendStatusNotice'
import LoadingSpinner from '@/components/LoadingSpinner'
import { readJsonResponse } from '@/lib/http'
import { useBotOverview } from '@/lib/useBotOverview'

function formatEur(value) {
  return new Intl.NumberFormat('nl-NL', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(Number(value ?? 0))
}

function RiskCard({ label, value, note, valueClass = 'text-white' }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${valueClass}`}>{value}</p>
      <p className="mt-2 text-xs text-zinc-600">{note}</p>
    </div>
  )
}

export default function RiskCenterPage() {
  const { payload, loading, error } = useBotOverview('Failed to load risk center')
  const [simulation, setSimulation] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [simulationError, setSimulationError] = useState('')
  const [form, setForm] = useState({
    equity: 160000,
    dayStartEquity: 160000,
    estimatedTradeRisk: 400,
  })

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitting(true)
    setSimulationError('')
    const response = await fetch('/api/bot/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    const data = await readJsonResponse(response)
    setSubmitting(false)
    if (!response.ok) {
      setSimulation(null)
      setSimulationError(data.error || 'Failed to run simulation')
      return
    }
    setSimulation(data.data ?? null)
  }

  const snapshot = payload?.risk?.data ?? {}
  const ftmo = snapshot.ftmo_status ?? {}
  const result = simulation ?? null

  useEffect(() => {
    if (!payload) return

    const risk = payload?.risk?.data ?? {}
    setForm({
      equity: Number(risk.equity ?? 160000),
      dayStartEquity: Number(risk.day_start_equity ?? risk.equity ?? 160000),
      estimatedTradeRisk: Number(risk.estimated_trade_risk ?? 400),
    })
  }, [payload])

  if (loading) return <LoadingSpinner center />
  if (error && !payload) {
    return <div className="rounded-xl border border-red-900 bg-red-950/40 px-5 py-4 text-sm text-red-300">{error}</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">FTMO Oversight</p>
        <h1 className="mt-2 text-2xl font-bold text-white">Risk Center</h1>
        <p className="mt-1 text-sm text-zinc-500">Current FTMO posture and downside simulation before new exposure.</p>
      </div>

      <BackendStatusNotice system={payload?.system} />

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <RiskCard label="Risk Level" value={String(ftmo.risk_level || 'unknown').toUpperCase()} note="Combined daily and total buffer posture." valueClass={ftmo.risk_level === 'red' ? 'text-red-400' : ftmo.risk_level === 'yellow' ? 'text-amber-400' : 'text-emerald-400'} />
        <RiskCard label="Daily Remaining" value={formatEur(ftmo.daily_remaining ?? 0)} note="Remaining room before the daily loss limit." />
        <RiskCard label="Total Remaining" value={formatEur(ftmo.total_remaining ?? 0)} note="Remaining room before the max-loss limit." />
        <RiskCard label="Estimated Trade Risk" value={formatEur(snapshot.estimated_trade_risk ?? 0)} note="Current risk estimate used by the backend snapshot." />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_340px]">
        <form onSubmit={handleSubmit} className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Buffer Simulation</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <label className="space-y-1">
              <span className="text-xs text-zinc-500">Current equity</span>
              <input type="number" value={form.equity} onChange={(event) => setForm((prev) => ({ ...prev, equity: Number(event.target.value) }))} className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-emerald-600 focus:outline-none" />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-zinc-500">Day-start equity</span>
              <input type="number" value={form.dayStartEquity} onChange={(event) => setForm((prev) => ({ ...prev, dayStartEquity: Number(event.target.value) }))} className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-emerald-600 focus:outline-none" />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-zinc-500">Estimated trade risk</span>
              <input type="number" value={form.estimatedTradeRisk} onChange={(event) => setForm((prev) => ({ ...prev, estimatedTradeRisk: Number(event.target.value) }))} className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-emerald-600 focus:outline-none" />
            </label>
          </div>

          <button type="submit" disabled={submitting} className="mt-5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60">
            {submitting ? 'Running...' : 'Run simulation'}
          </button>

          {simulationError ? (
            <div className="mt-4 rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {simulationError}
            </div>
          ) : null}

          {result ? (
            <div className="mt-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
              <RiskCard label="Projected Level" value={String(result.risk_level || 'unknown').toUpperCase()} note="Simulated FTMO posture." valueClass={result.risk_level === 'red' ? 'text-red-400' : result.risk_level === 'yellow' ? 'text-amber-400' : 'text-emerald-400'} />
              <RiskCard label="Daily Buffer" value={`${Number(result.daily_buffer_pct ?? 0).toFixed(1)}%`} note="Remaining daily buffer after the scenario." />
              <RiskCard label="Total Buffer" value={`${Number(result.total_buffer_pct ?? 0).toFixed(1)}%`} note="Remaining total buffer after the scenario." />
              <RiskCard label="Overall OK" value={result.overall_ok ? 'YES' : 'NO'} note="Combined daily and total safety status." valueClass={result.overall_ok ? 'text-emerald-400' : 'text-red-400'} />
            </div>
          ) : null}
        </form>

        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-sm font-semibold text-white">Current Posture</h2>
          <div className="mt-4 space-y-3 text-sm text-zinc-300">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <span className="text-zinc-500">Daily status</span>
              <span>{ftmo.daily_ok ? 'Compliant' : 'At risk'}</span>
            </div>
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <span className="text-zinc-500">Total status</span>
              <span>{ftmo.total_ok ? 'Compliant' : 'At risk'}</span>
            </div>
            <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
              <span className="text-zinc-500">Stress score</span>
              <span>{Number(snapshot.stress_score ?? 0).toFixed(0)} / 100</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-500">Fail probability</span>
              <span>{(Number(snapshot.fail_probability ?? 0) * 100).toFixed(1)}%</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
