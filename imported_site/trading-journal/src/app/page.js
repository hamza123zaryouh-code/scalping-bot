'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import LoadingSpinner from '@/components/LoadingSpinner'
import QuickTradeModal from '@/components/QuickTradeModal'
import {
  SATISFACTION_EMOJIS,
  buildAgendaSummary,
  buildDashboardStats,
  buildDisciplineStats,
  buildDrawdown,
  buildEmojiSummary,
  buildEquityCurve,
  buildFtmoStatus,
  buildRMultipleStats,
  buildStatistics,
  buildStreaks,
  buildTradeGoals,
  formatCurrency,
  getStatusLabelKey,
  tradesWithProfileCurrency,
  usesIndicativeFx,
} from '@/lib/tradeUtils'
import { useTranslation } from '@/lib/i18n'
import { useProfile } from '@/components/ProfileProvider'
import { apiFetch } from '@/lib/apiFetch'
import { formatDate, pnlColor, typeBadgeClass } from '@/lib/utils'

// ─── Sub-components ────────────────────────────────────────────────────────────

function TopStatCard({ label, value, valueClass, footnote, footnoteClass }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900 px-5 py-4">
      <p className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">{label}</p>
      <p className={`text-3xl font-black tracking-tight leading-none ${valueClass ?? 'text-white'}`}>{value}</p>
      {footnote && (
        <p className={`text-xs ${footnoteClass ?? 'text-zinc-600'}`}>{footnote}</p>
      )}
    </div>
  )
}

function FtmoBar({ label, used, remaining, limit, pct, status, currency }) {
  const barColor =
    status === 'breached' ? 'bg-red-600' :
    status === 'danger'   ? 'bg-red-500' :
    status === 'warning'  ? 'bg-amber-500' :
                            'bg-emerald-500'

  const textColor =
    status === 'breached' || status === 'danger' ? 'text-red-400' :
    status === 'warning'                          ? 'text-amber-400' :
                                                    'text-emerald-400'

  const dotColor =
    status === 'breached' || status === 'danger' ? 'bg-red-500' :
    status === 'warning'                          ? 'bg-amber-500' :
                                                    'bg-emerald-500'

  // pct is the remaining %, so bar width = remaining buffer
  const fillPct = Math.max(0, Math.min(100, pct))

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${dotColor}`} />
          <span className="text-sm font-medium text-zinc-300">{label}</span>
        </div>
        <span className={`text-sm font-bold ${textColor}`}>
          {formatCurrency(remaining, currency)} left
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-xs text-zinc-600">
        <span>{formatCurrency(used, currency)} used</span>
        <span>Limit {formatCurrency(limit, currency)}</span>
      </div>
    </div>
  )
}

function StatRow({ label, value, valueClass }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-zinc-800/50 last:border-0">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className={`text-sm font-bold tabular-nums ${valueClass ?? 'text-white'}`}>{value}</span>
    </div>
  )
}

function GoalProgress({ label, pct, displayValue, status }) {
  const barColor =
    status === 'danger'  ? 'bg-red-500' :
    status === 'warning' ? 'bg-amber-500' :
    status === 'safe'    ? 'bg-emerald-500' :
                           'bg-zinc-600'

  const valColor =
    status === 'danger'  ? 'text-red-400' :
    status === 'warning' ? 'text-amber-400' :
    status === 'safe'    ? 'text-emerald-400' :
                           'text-zinc-400'

  const borderColor =
    status === 'danger'  ? 'border-red-900/30' :
    status === 'warning' ? 'border-amber-900/30' :
    status === 'safe'    ? 'border-emerald-900/30' :
                           'border-zinc-800'

  return (
    <div className={`rounded-xl border px-4 py-3.5 space-y-2 bg-zinc-900 ${borderColor}`}>
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-widest text-zinc-500">{label}</p>
        <p className={`text-sm font-bold tabular-nums ${valColor}`}>{displayValue}</p>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
    </div>
  )
}

// ─── Main Dashboard ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const { t } = useTranslation()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(null)
  const [quickTradeOpen, setQuickTradeOpen] = useState(false)

  const fetchTrades = useCallback(async () => {
    try {
      const res = await apiFetch('/api/trades')
      const data = await res.json()
      if (!res.ok || data.error) {
        setFetchError(data.error || t('common.loadError'))
        return
      }

      setFetchError(null)
      setTrades(data.trades ?? [])
    } catch {
      setFetchError(t('common.loadError'))
    }
  }, [t])

  useEffect(() => {
    apiFetch('/api/trades')
      .then((r) => r.json())
      .then((d) => {
        if (d.error) setFetchError(d.error)
        else setTrades(d.trades ?? [])
      })
      .catch(() => setFetchError(t('common.loadError')))
      .finally(() => setLoading(false))
  }, [t])

  const displayTrades = useMemo(() => tradesWithProfileCurrency(trades, profile), [trades, profile])
  const stats      = useMemo(() => buildDashboardStats(displayTrades), [displayTrades])
  const fullStats  = useMemo(() => buildStatistics(displayTrades),     [displayTrades])
  const emojiSummary    = useMemo(() => buildEmojiSummary(displayTrades),            [displayTrades])
  const agendaSummary   = useMemo(() => buildAgendaSummary(displayTrades, 5),        [displayTrades])
  const recentTrades    = useMemo(() => displayTrades.slice(0, 5),                   [displayTrades])
  const ftmoStatus      = useMemo(() => buildFtmoStatus(displayTrades, profile),     [displayTrades, profile])
  const drawdown        = useMemo(() => buildDrawdown(displayTrades),                [displayTrades])
  const equityCurve     = useMemo(() => buildEquityCurve(displayTrades),             [displayTrades])
  const tradeGoals      = useMemo(() => buildTradeGoals(displayTrades, profile),     [displayTrades, profile])
  const streaks         = useMemo(() => buildStreaks(displayTrades),                 [displayTrades])
  const rMultiple       = useMemo(() => buildRMultipleStats(displayTrades, profile), [displayTrades, profile])
  const disciplineStats = useMemo(() => buildDisciplineStats(displayTrades),         [displayTrades])
  const hasEmojiData    = useMemo(() => SATISFACTION_EMOJIS.some((e) => emojiSummary[e] > 0), [emojiSummary])

  // Goal progress percentages (for progress bars)
  const tradeGoalPct = tradeGoals.maxTradesPerDay
    ? (tradeGoals.tradesToday / tradeGoals.maxTradesPerDay) * 100
    : 0
  const riskGoalPct = tradeGoals.maxRiskPerDay
    ? (tradeGoals.riskUsedToday / tradeGoals.maxRiskPerDay) * 100
    : 0
  const profitGoalPct = tradeGoals.dailyProfitTarget && tradeGoals.profitLossToday > 0
    ? (tradeGoals.profitLossToday / tradeGoals.dailyProfitTarget) * 100
    : 0

  // Worst overall FTMO status
  const ftmoOverallStatus = ftmoStatus
    ? (['breached', 'danger', 'warning', 'safe'].find(
        (s) => ftmoStatus.dailyStatus === s || ftmoStatus.maxStatus === s
      ) ?? 'safe')
    : null

  if (loading) return <LoadingSpinner center />

  if (fetchError) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center px-4">
        <svg className="h-8 w-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
        <p className="text-sm font-medium text-zinc-300">{fetchError}</p>
        <button
          onClick={() => { setFetchError(null); setLoading(true); fetchTrades().finally(() => setLoading(false)) }}
          className="rounded-lg bg-zinc-800 px-4 py-2 text-sm text-zinc-300 hover:text-white"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-5">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">{t('dashboard.title')}</h1>
          <p className="mt-0.5 text-xs text-zinc-500">{t('dashboard.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setQuickTradeOpen(true)}
            className="rounded-lg border border-zinc-700 px-3.5 py-2 text-sm font-semibold text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-white"
          >
            {t('dashboard.quickTrade')}
          </button>
          <Link
            href="/trades/new"
            className="rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-500"
          >
            + {t('dashboard.newTrade')}
          </Link>
        </div>
      </div>

      {/* ── Banners ──────────────────────────────────────────────────────── */}
      {trades.length === 0 && (
        <div className="rounded-xl border border-emerald-800/40 bg-emerald-950/30 px-5 py-5">
          <p className="font-semibold text-emerald-300">{t('dashboard.onboardingTitle')}</p>
          <p className="mt-1 text-sm text-emerald-400/80">{t('dashboard.onboardingMessage')}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href="/trades/new" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500">
              {t('dashboard.emptyAction')}
            </Link>
            {!profile?.accountBalance && (
              <Link href="/profile" className="rounded-lg border border-emerald-700 px-4 py-2 text-sm font-semibold text-emerald-300 hover:bg-emerald-900/40">
                {t('dashboard.onboardingProfile')}
              </Link>
            )}
          </div>
        </div>
      )}

      {trades.length > 0 && !profile?.accountBalance && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-900/60 bg-amber-950/20 px-5 py-4">
          <svg className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <div>
            <p className="text-sm font-semibold text-amber-300">{t('dashboard.accountBalanceMissing')}</p>
            <p className="mt-0.5 text-xs text-amber-200/70">{t('dashboard.accountBalanceMissingHint')}</p>
            <Link href="/profile" className="mt-2 inline-block rounded-lg border border-amber-700 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-900/30">
              {t('dashboard.onboardingProfile')}
            </Link>
          </div>
        </div>
      )}

      {usesIndicativeFx(profile) && (
        <p className="rounded-lg border border-amber-900/40 bg-amber-950/10 px-4 py-2 text-xs text-amber-400">
          {t('dashboard.indicativeFx')}
        </p>
      )}

      {/* ── 1. TOP STATS ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <TopStatCard
          label={t('dashboard.totalProfit')}
          value={formatCurrency(stats.totalProfitLoss, currency)}
          valueClass={stats.totalProfitLoss >= 0 ? 'text-emerald-400' : 'text-red-400'}
          footnote={`${stats.totalTrades} trades total`}
        />
        <TopStatCard
          label={t('dashboard.profitToday')}
          value={formatCurrency(stats.profitLossToday, currency)}
          valueClass={stats.profitLossToday >= 0 ? 'text-emerald-400' : 'text-red-400'}
          footnote={`${tradeGoals.tradesToday} trades today`}
        />
        <TopStatCard
          label={t('dashboard.winRate')}
          value={`${stats.winRate}%`}
          valueClass={
            stats.winRate >= 60 ? 'text-emerald-400' :
            stats.winRate >= 45 ? 'text-amber-400' :
            stats.closedTrades === 0 ? 'text-zinc-500' :
            'text-red-400'
          }
          footnote={`${stats.winningTrades}W · ${stats.losingTrades}L`}
        />
        <TopStatCard
          label={t('dashboard.currentDrawdown')}
          value={drawdown.currentDrawdown > 0 ? formatCurrency(-drawdown.currentDrawdown, currency) : '—'}
          valueClass={drawdown.currentDrawdown > 0 ? 'text-red-400' : 'text-zinc-600'}
          footnote={drawdown.maxDrawdown > 0 ? `Max: ${formatCurrency(-drawdown.maxDrawdown, currency)}` : 'No drawdown'}
        />
      </div>

      {/* ── 2. FTMO / RISK PANEL ─────────────────────────────────────────── */}
      {ftmoStatus ? (
        <section className="rounded-xl border border-zinc-700 bg-zinc-900 overflow-hidden">
          <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-3.5">
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
              </svg>
              <h2 className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-400">
                {t('dashboard.ftmoStatus')}
              </h2>
            </div>
            <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
              ftmoOverallStatus === 'breached' ? 'bg-red-950 text-red-400' :
              ftmoOverallStatus === 'danger'   ? 'bg-red-950/60 text-red-400' :
              ftmoOverallStatus === 'warning'  ? 'bg-amber-950 text-amber-400' :
                                                 'bg-emerald-950 text-emerald-400'
            }`}>
              {ftmoOverallStatus === 'breached' ? 'Breached' :
               ftmoOverallStatus === 'danger'   ? 'Danger' :
               ftmoOverallStatus === 'warning'  ? 'Warning' :
               'Safe'}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-6 px-5 py-5 sm:grid-cols-2">
            <FtmoBar
              label={t('dashboard.dailyLoss')}
              used={ftmoStatus.dailyLossUsed}
              remaining={ftmoStatus.dailyRemaining}
              limit={ftmoStatus.dailyLimit}
              pct={ftmoStatus.dailyPct}
              status={ftmoStatus.dailyStatus}
              currency={currency}
            />
            <FtmoBar
              label={t('dashboard.maxLoss')}
              used={ftmoStatus.maxLossUsed}
              remaining={ftmoStatus.maxRemaining}
              limit={ftmoStatus.maxLimit}
              pct={ftmoStatus.maxPct}
              status={ftmoStatus.maxStatus}
              currency={currency}
            />
          </div>
        </section>
      ) : trades.length > 0 ? (
        <div className="flex items-center justify-between rounded-xl border border-zinc-800 bg-zinc-900/50 px-5 py-3.5">
          <p className="text-sm text-zinc-600">{t('dashboard.noFtmoConfig')}</p>
          <Link href="/profile" className="text-xs text-emerald-400 hover:text-emerald-300">
            {t('nav.profile')} →
          </Link>
        </div>
      ) : null}

      {/* ── 3. PERFORMANCE ───────────────────────────────────────────────── */}
      {displayTrades.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">

          {/* Equity curve */}
          <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
            <h2 className="mb-4 text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">
              {t('statistics.equityCurve')}
            </h2>
            {equityCurve.length > 1 ? (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={equityCurve} margin={{ top: 4, right: 4, left: 0, bottom: 4 }}>
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: '#52525b' }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(d) => d.slice(5)}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: '#52525b' }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => formatCurrency(v, currency)}
                    width={70}
                  />
                  <Tooltip
                    contentStyle={{ background: '#18181b', border: '1px solid #27272a', borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: '#71717a' }}
                    formatter={(value) => [formatCurrency(value, currency), t('statistics.equityCurve')]}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: '#10b981', strokeWidth: 0 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-[200px] items-center justify-center text-sm text-zinc-700">
                Log more trades to see equity curve
              </div>
            )}
          </section>

          {/* Compact stat list */}
          <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
            <h2 className="mb-1 text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">Performance</h2>
            <div>
              <StatRow
                label={t('dashboard.winRate')}
                value={`${stats.winRate}%`}
                valueClass={stats.winRate >= 60 ? 'text-emerald-400' : stats.winRate >= 45 ? 'text-amber-400' : 'text-red-400'}
              />
              <StatRow
                label={t('dashboard.averageWin')}
                value={formatCurrency(stats.avgWin, currency)}
                valueClass="text-emerald-400"
              />
              <StatRow
                label={t('dashboard.averageLoss')}
                value={formatCurrency(stats.avgLoss, currency)}
                valueClass="text-red-400"
              />
              <StatRow
                label="Profit Factor"
                value={fullStats.profitFactor != null ? fullStats.profitFactor.toFixed(2) : '—'}
                valueClass={
                  fullStats.profitFactor == null ? 'text-zinc-600' :
                  fullStats.profitFactor >= 1.5  ? 'text-emerald-400' :
                  fullStats.profitFactor >= 1    ? 'text-amber-400' :
                                                   'text-red-400'
                }
              />
              <StatRow
                label={t('dashboard.avgR')}
                value={
                  rMultiple.avgR != null
                    ? `${rMultiple.avgR >= 0 ? '+' : ''}${rMultiple.avgR.toFixed(2)}R`
                    : '—'
                }
                valueClass={
                  rMultiple.avgR == null ? 'text-zinc-600' :
                  rMultiple.avgR >= 0    ? 'text-emerald-400' :
                                           'text-red-400'
                }
              />
              <StatRow
                label="Best Trade"
                value={stats.bestTrade ? formatCurrency(stats.bestTrade.profitLoss, currency) : '—'}
                valueClass="text-emerald-400"
              />
              <StatRow
                label="Worst Trade"
                value={stats.worstTrade ? formatCurrency(stats.worstTrade.profitLoss, currency) : '—'}
                valueClass="text-red-400"
              />
            </div>
          </section>
        </div>
      )}

      {/* ── 4. DISCIPLINE + 5. STREAKS ───────────────────────────────────── */}
      {displayTrades.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">

          {/* Discipline */}
          <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">Discipline</h2>
              {disciplineStats.total > 0 && (
                <span className={`text-sm font-bold ${
                  disciplineStats.goodPct >= 70 ? 'text-emerald-400' :
                  disciplineStats.goodPct >= 50 ? 'text-amber-400' :
                  'text-red-400'
                }`}>
                  {disciplineStats.goodPct}% consistent
                </span>
              )}
            </div>
            {hasEmojiData ? (
              <div className="space-y-3">
                {SATISFACTION_EMOJIS.map((emoji) => {
                  const count = emojiSummary[emoji] ?? 0
                  const pct = disciplineStats.total > 0
                    ? Math.round((count / disciplineStats.total) * 100)
                    : 0
                  return (
                    <div key={emoji} className="flex items-center gap-3">
                      <span className="w-6 text-center text-base leading-none shrink-0">{emoji}</span>
                      <div className="flex-1 h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-zinc-500 transition-all duration-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-6 text-right text-xs text-zinc-600 tabular-nums">{count > 0 ? count : ''}</span>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="text-sm text-zinc-700">Rate your trades to track discipline</p>
            )}
          </section>

          {/* Streaks */}
          <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
            <h2 className="mb-4 text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-500">Streaks</h2>
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-lg bg-zinc-800/50 px-4 py-3.5">
                <div className="flex items-center gap-3">
                  <span className="text-2xl leading-none">{streaks.currentWinStreak > 0 ? '🔥' : '—'}</span>
                  <div>
                    <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Win Streak</p>
                    <p className={`text-2xl font-black leading-none tabular-nums ${streaks.currentWinStreak > 0 ? 'text-emerald-400' : 'text-zinc-700'}`}>
                      {streaks.currentWinStreak}
                    </p>
                  </div>
                </div>
                <p className="text-xs text-zinc-600">Best: {streaks.longestWinStreak}</p>
              </div>
              <div className="flex items-center justify-between rounded-lg bg-zinc-800/50 px-4 py-3.5">
                <div className="flex items-center gap-3">
                  <span className="text-2xl leading-none">{streaks.currentLossStreak > 0 ? '❄️' : '—'}</span>
                  <div>
                    <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Loss Streak</p>
                    <p className={`text-2xl font-black leading-none tabular-nums ${streaks.currentLossStreak > 0 ? 'text-red-400' : 'text-zinc-700'}`}>
                      {streaks.currentLossStreak}
                    </p>
                  </div>
                </div>
                <p className="text-xs text-zinc-600">Worst: {streaks.longestLossStreak}</p>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* ── 6. RECENT TRADES ─────────────────────────────────────────────── */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900">
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <h2 className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-400">
            {t('dashboard.recentTrades')}
          </h2>
          <Link href="/trades" className="text-xs text-emerald-400 transition-colors hover:text-emerald-300">
            {t('dashboard.viewAll')} →
          </Link>
        </div>

        {recentTrades.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <p className="text-sm text-zinc-600">{t('dashboard.emptyMessage')}</p>
            <Link
              href="/trades/new"
              className="mt-4 inline-block rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500"
            >
              {t('dashboard.emptyAction')}
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-zinc-800/50">
            {recentTrades.map((trade) => (
              <Link
                key={trade.id}
                href={`/trades/${trade.id}`}
                className="flex items-center justify-between gap-3 px-5 py-3.5 transition-colors hover:bg-zinc-800/40"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${typeBadgeClass(trade.tradeType)}`}>
                    {trade.tradeType === 'Buy' ? t('trades.buy') : t('trades.sell')}
                  </span>
                  <span className="text-sm font-semibold text-white truncate">{trade.symbol}</span>
                  <span className="hidden sm:inline text-xs text-zinc-600">{formatDate(trade.date)}</span>
                  {trade.satisfactionEmoji && (
                    <span className="text-sm leading-none">{trade.satisfactionEmoji}</span>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <p className={`text-sm font-bold tabular-nums ${pnlColor(trade.profitLoss)}`}>
                    {formatCurrency(trade.profitLoss, currency)}
                  </p>
                  <p className="text-[10px] text-zinc-600">{t(getStatusLabelKey(trade.status))}</p>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* ── 7. CALENDAR PREVIEW + 8. GOALS ───────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">

        {/* Calendar preview */}
        <section className="rounded-xl border border-zinc-800 bg-zinc-900">
          <div className="border-b border-zinc-800 px-5 py-4">
            <h2 className="text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-400">
              {t('dashboard.agendaSummary')}
            </h2>
          </div>
          {agendaSummary.length === 0 ? (
            <p className="px-5 py-8 text-sm text-zinc-700">{t('dashboard.noAgendaData')}</p>
          ) : (
            <div className="divide-y divide-zinc-800/50">
              {agendaSummary.map((day) => (
                <Link
                  key={day.date}
                  href={`/calendar?date=${day.date}`}
                  className="flex items-center justify-between gap-3 px-5 py-3 transition-colors hover:bg-zinc-800/40"
                >
                  <div>
                    <p className="text-sm font-medium text-white">{formatDate(day.date)}</p>
                    <p className="text-xs text-zinc-600">{t('dashboard.agendaTrades', { count: day.tradeCount })}</p>
                  </div>
                  <p className={`text-sm font-bold tabular-nums ${day.totalProfitLoss >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatCurrency(day.totalProfitLoss, currency)}
                  </p>
                </Link>
              ))}
            </div>
          )}
        </section>

        {/* Goals tracking */}
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="mb-4 text-[10px] font-bold uppercase tracking-[0.15em] text-zinc-400">
            Today&apos;s Goals
          </h2>
          <div className="space-y-3">
            <GoalProgress
              label={t('dashboard.goalTrades')}
              pct={tradeGoalPct}
              displayValue={
                tradeGoals.maxTradesPerDay
                  ? `${tradeGoals.tradesToday} / ${tradeGoals.maxTradesPerDay}`
                  : String(tradeGoals.tradesToday)
              }
              status={tradeGoals.tradesStatus}
            />
            <GoalProgress
              label={t('dashboard.goalRisk')}
              pct={riskGoalPct}
              displayValue={
                tradeGoals.maxRiskPerDay
                  ? `${formatCurrency(tradeGoals.riskUsedToday, currency)} / ${formatCurrency(tradeGoals.maxRiskPerDay, currency)}`
                  : formatCurrency(tradeGoals.riskUsedToday, currency)
              }
              status={tradeGoals.riskStatus}
            />
            <GoalProgress
              label={t('dashboard.goalProfit')}
              pct={profitGoalPct}
              displayValue={
                tradeGoals.dailyProfitTarget
                  ? `${formatCurrency(tradeGoals.profitLossToday, currency)} / ${formatCurrency(tradeGoals.dailyProfitTarget, currency)}`
                  : formatCurrency(tradeGoals.profitLossToday, currency)
              }
              status={tradeGoals.profitStatus}
            />
          </div>
        </section>
      </div>

      <QuickTradeModal
        isOpen={quickTradeOpen}
        onClose={() => setQuickTradeOpen(false)}
        onSuccess={fetchTrades}
        currency={currency}
        profile={profile}
      />
    </div>
  )
}
