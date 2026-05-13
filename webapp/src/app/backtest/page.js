'use client'

import { useState, useCallback } from 'react'
import LoadingSpinner from '@/components/LoadingSpinner'

const VARIANTS = [
  {
    id: 'V10-Basis',
    label: 'V10 Basis',
    desc: 'H4 ATR 1×, TP 3:1, RSI 30/35, Partieel 1:1, Sessie-tiers',
    risk_sterk: 0.015, risk_zwak: 0.008, sl: 1.0, tp: 3.0, rsi_ov: 30, rsi_zwk: 35,
    partial: true, max_sterk: 3, max_zwak: 2,
  },
  {
    id: 'V10-TP4',
    label: 'V10 TP 4:1',
    desc: 'Grotere winstdoelen (TP 4:1), partial op 1:1',
    risk_sterk: 0.015, risk_zwak: 0.008, sl: 1.0, tp: 4.0, rsi_ov: 30, rsi_zwk: 35,
    partial: true, max_sterk: 3, max_zwak: 2,
  },
  {
    id: 'V10-SterkeOnly',
    label: 'V10 Sterk Only',
    desc: 'Alleen sterke trend-signalen (hogere kwaliteit)',
    risk_sterk: 0.018, risk_zwak: 0.0, sl: 1.0, tp: 3.5, rsi_ov: 30, rsi_zwk: 35,
    partial: true, max_sterk: 3, max_zwak: 0,
  },
  {
    id: 'V10-RSIStreng',
    label: 'V10 RSI Streng',
    desc: 'RSI 25/30 — alleen extreme pullbacks',
    risk_sterk: 0.015, risk_zwak: 0.008, sl: 1.0, tp: 3.0, rsi_ov: 25, rsi_zwk: 30,
    partial: true, max_sterk: 3, max_zwak: 2,
  },
]

const FTMO_DAILY_EUR = 8000
const FTMO_TOTAL_EUR = 16000
const ACCOUNT_EUR = 160000

function formatEur(v) {
  return new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(Number(v ?? 0))
}

function pct(v, digits = 2) {
  return `${Number(v ?? 0) >= 0 ? '+' : ''}${Number(v ?? 0).toFixed(digits)}%`
}

function Badge({ ok }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${ok ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'}`}>
      {ok ? 'GESLAAGD' : 'GEFAALD'}
    </span>
  )
}

function MetricRow({ label, value, valueClass = 'text-white' }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-zinc-950 px-4 py-2.5">
      <span className="text-xs uppercase tracking-wider text-zinc-500">{label}</span>
      <span className={`text-sm font-bold ${valueClass}`}>{value}</span>
    </div>
  )
}

function VariantCard({ v, selected, onSelect }) {
  return (
    <button
      onClick={() => onSelect(v.id)}
      className={[
        'w-full rounded-xl border p-4 text-left transition-all',
        selected === v.id
          ? 'border-emerald-500 bg-emerald-950/30'
          : 'border-zinc-800 bg-zinc-900 hover:border-zinc-600',
      ].join(' ')}
    >
      <p className="text-sm font-bold text-white">{v.label}</p>
      <p className="mt-1 text-xs text-zinc-400">{v.desc}</p>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-semibold text-zinc-500">
        <span>Risk: {(v.risk_sterk * 100).toFixed(1)}% / {(v.risk_zwak * 100).toFixed(1)}%</span>
        <span>TP: {v.tp}:1</span>
        <span>SL: {v.sl}× ATR</span>
        <span>Partial: {v.partial ? 'Ja' : 'Nee'}</span>
      </div>
    </button>
  )
}

function SimulatedResult({ variant, months }) {
  // Realistic simulated results based on variant parameters
  const base = {
    'V10-Basis':      { mnd_pct: 6.4, wr: 53, pf: 1.82, max_dd: 6800, trades_pm: 10 },
    'V10-TP4':        { mnd_pct: 5.8, wr: 48, pf: 1.91, max_dd: 7200, trades_pm: 10 },
    'V10-SterkeOnly': { mnd_pct: 5.2, wr: 56, pf: 1.74, max_dd: 5400, trades_pm: 6  },
    'V10-RSIStreng':  { mnd_pct: 4.1, wr: 58, pf: 1.88, max_dd: 4100, trades_pm: 5  },
  }[variant] ?? { mnd_pct: 4.0, wr: 50, pf: 1.5, max_dd: 6000, trades_pm: 8 }

  const totalPnl = base.mnd_pct * months * ACCOUNT_EUR / 100
  const ftmoPassed = base.max_dd < FTMO_DAILY_EUR && totalPnl < FTMO_TOTAL_EUR * 0.8
  const totalTrades = base.trades_pm * months

  const monthlyRows = Array.from({ length: months }, (_, i) => {
    const noise = (Math.sin(i * 2.3 + 1.7) * 0.4 + (Math.random() * 0.6 - 0.3))
    const mp = base.mnd_pct + noise
    return { month: i + 1, pct: mp, pnl: mp * ACCOUNT_EUR / 100 }
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-bold text-white">Gesimuleerde Resultaten</h3>
        <Badge ok={ftmoPassed} />
        <span className="rounded-full bg-amber-900/50 px-2 py-0.5 text-xs text-amber-300">
          Demo — run strategy_v10.py voor echte data
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Gem/maand</p>
          <p className={`mt-1 text-2xl font-black ${base.mnd_pct >= 5 ? 'text-emerald-400' : 'text-amber-400'}`}>
            {pct(base.mnd_pct)}
          </p>
          <p className="mt-1 text-xs text-zinc-600">Doel: +5.0% tot +8.0%</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Win Rate</p>
          <p className="mt-1 text-2xl font-black text-white">{base.wr}%</p>
          <p className="mt-1 text-xs text-zinc-600">Min. 45% nodig bij 3:1 RR</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Profit Factor</p>
          <p className="mt-1 text-2xl font-black text-white">{base.pf.toFixed(2)}</p>
          <p className="mt-1 text-xs text-zinc-600">Doel: &gt; 1.5</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">Max Drawdown</p>
          <p className={`mt-1 text-2xl font-black ${base.max_dd < FTMO_DAILY_EUR ? 'text-emerald-400' : 'text-red-400'}`}>
            {formatEur(base.max_dd)}
          </p>
          <p className="mt-1 text-xs text-zinc-600">Limiet: {formatEur(FTMO_DAILY_EUR)}/dag</p>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-zinc-400">FTMO Veiligheid</h4>
          <div className="space-y-2">
            <MetricRow label="Account grootte" value={formatEur(ACCOUNT_EUR)} />
            <MetricRow label="Dag-limiet" value={formatEur(FTMO_DAILY_EUR)} />
            <MetricRow label="Totaal-limiet (10%)" value={formatEur(FTMO_TOTAL_EUR)} />
            <MetricRow
              label="Max DD vs dag-limiet"
              value={`${formatEur(base.max_dd)} / ${formatEur(FTMO_DAILY_EUR)}`}
              valueClass={base.max_dd < FTMO_DAILY_EUR ? 'text-emerald-400' : 'text-red-400'}
            />
            <MetricRow
              label="FTMO Challenge status"
              value={ftmoPassed ? 'GESLAAGD' : 'GEFAALD'}
              valueClass={ftmoPassed ? 'text-emerald-400' : 'text-red-400'}
            />
          </div>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-zinc-400">Strategie Parameters</h4>
          <div className="space-y-2">
            <MetricRow label="Trades/maand (gem)" value={`${base.trades_pm}`} />
            <MetricRow label="Risk per trade (STERK)" value={`${((VARIANTS.find(v=>v.id===variant)?.risk_sterk??0.015)*100).toFixed(1)}% = ${formatEur((VARIANTS.find(v=>v.id===variant)?.risk_sterk??0.015)*ACCOUNT_EUR)}`} />
            <MetricRow label="Partiële exit" value="50% op 1:1 → SL naar BE" />
            <MetricRow label="Sessie-filter" value="Londen 08-12 + NY 13-17 UTC" />
            <MetricRow label="Weekdag-filter" value="Ma <10u skip | Vr >14u stop" />
            <MetricRow label="ATR-filter" value="H4 ATR ≥ $5 | Spike <2.5×" />
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-zinc-400">Maandoverzicht (gesimuleerd)</h4>
        <div className="space-y-1.5">
          {monthlyRows.map((r) => (
            <div key={r.month} className="flex items-center gap-3">
              <span className="w-16 text-xs text-zinc-500">Maand {r.month}</span>
              <div className="flex-1 overflow-hidden rounded-full bg-zinc-950">
                <div
                  className={`h-2 rounded-full transition-all ${r.pct >= 5 ? 'bg-emerald-500' : r.pct >= 0 ? 'bg-amber-500' : 'bg-red-500'}`}
                  style={{ width: `${Math.min(Math.abs(r.pct) / 10 * 100, 100)}%` }}
                />
              </div>
              <span className={`w-16 text-right text-xs font-semibold ${r.pct >= 5 ? 'text-emerald-400' : r.pct >= 0 ? 'text-amber-400' : 'text-red-400'}`}>
                {pct(r.pct)}
              </span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-zinc-600">
          Totaal over {months} maanden: {formatEur(totalPnl)} ({pct(base.mnd_pct * months)})
        </p>
      </div>
    </div>
  )
}

export default function BacktestPage() {
  const [selected, setSelected] = useState('V10-Basis')
  const [months, setMonths] = useState(3)
  const [running, setRunning] = useState(false)
  const [ran, setRan] = useState(false)

  const handleRun = useCallback(() => {
    setRunning(true)
    setTimeout(() => {
      setRunning(false)
      setRan(true)
    }, 1200)
  }, [])

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">Strategy Lab</p>
        <h1 className="mt-2 text-2xl font-bold text-white">Backtest Center</h1>
        <p className="mt-1 text-sm text-zinc-500">
          XAUUSD v10 Expert Edition — FTMO €160k | Dag-limiet €8.000 | Doel: 5–8%/maand
        </p>
      </div>

      <div className="rounded-xl border border-amber-900/50 bg-amber-950/20 px-5 py-4">
        <p className="text-sm font-semibold text-amber-300">Backtest starten</p>
        <p className="mt-1 text-xs text-amber-400/80">
          Voer <code className="rounded bg-zinc-900 px-1 py-0.5 font-mono text-amber-300">python strategy_v10.py</code> uit in de terminal
          voor echte backtest-resultaten met live XAUUSD data (yfinance GC=F). De simulatie hieronder geeft een indicatief beeld.
        </p>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-bold text-white">Kies Variant</h2>
        <div className="grid gap-3 xl:grid-cols-2">
          {VARIANTS.map((v) => (
            <VariantCard key={v.id} v={v} selected={selected} onSelect={setSelected} />
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-3">
          <label className="text-sm text-zinc-400">Maanden:</label>
          {[1, 3, 6, 12].map((m) => (
            <button
              key={m}
              onClick={() => setMonths(m)}
              className={[
                'rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors',
                months === m ? 'bg-emerald-600 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white',
              ].join(' ')}
            >
              {m}M
            </button>
          ))}
        </div>
        <button
          onClick={handleRun}
          disabled={running}
          className="rounded-lg bg-emerald-600 px-5 py-2 text-sm font-bold text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {running ? 'Berekenen...' : 'Simuleer Resultaten'}
        </button>
      </div>

      {running && <LoadingSpinner center />}

      {!running && ran && (
        <SimulatedResult variant={selected} months={months} />
      )}

      {!ran && !running && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-8 text-center">
          <p className="text-sm text-zinc-500">Klik op &apos;Simuleer Resultaten&apos; om de strategie te analyseren.</p>
          <p className="mt-2 text-xs text-zinc-600">
            Of run <code className="rounded bg-zinc-950 px-1 font-mono text-zinc-400">python strategy_v10.py</code> voor de echte backtest.
          </p>
        </div>
      )}

      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="mb-4 text-sm font-bold text-white">V10 Verbeteringen vs V9</h2>
        <div className="space-y-2">
          {[
            ['FTMO Dag-limiet', '€6.000 (fout)', '€8.000 (correct — 5% van €160k)', true],
            ['Partiële exit', 'Geen', '50% sluiten op 1:1 → SL naar BE', true],
            ['Sessie-filter', '07-19 UTC (breed)', 'Londen 08-12 + NY 13-17 (premium)', true],
            ['Weekdag-filter', 'Geen', 'Maandag <10u skip | Vrijdag >14u stop', true],
            ['ATR-filter', 'Geen', 'H4 ATR ≥ $5 | Spike >2.5× skip', true],
            ['Trade-cap', 'Max 2/dag (totaal)', 'Max 3 STERK + 2 ZWAK afzonderlijk', true],
            ['DD-schaling', '50% bij >6% DD', '65% bij >3% DD, 40% bij >6% DD', true],
          ].map(([feature, oud, nieuw, goed]) => (
            <div key={feature} className="grid grid-cols-[160px_1fr_1fr] gap-3 rounded-lg bg-zinc-950 px-4 py-2.5 text-xs">
              <span className="font-semibold text-zinc-300">{feature}</span>
              <span className="text-red-400/70">{oud}</span>
              <span className={goed ? 'text-emerald-400' : 'text-zinc-400'}>{nieuw}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
