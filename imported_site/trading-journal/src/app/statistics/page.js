'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useProfile } from '@/components/ProfileProvider'
import { apiFetch } from '@/lib/apiFetch'
import {
  buildDayOfWeekStats,
  buildDisciplineStats,
  buildDrawdown,
  buildEquityCurve,
  buildMonthlyStats,
  buildRMultipleStats,
  buildSessionStats,
  buildSetupTagStats,
  buildStatistics,
  buildStreaks,
  formatCurrency,
  tradesWithProfileCurrency,
  usesIndicativeFx,
} from '@/lib/tradeUtils'
import { useTranslation } from '@/lib/i18n'
import { formatDate } from '@/lib/utils'

function StatItem({ label, value, className = 'text-white' }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-xs uppercase tracking-wider text-zinc-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${className}`}>{value}</p>
    </div>
  )
}

function DisciplineBar({ label, pct, count, color }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-zinc-400">{label}</span>
        <span className="font-semibold text-white">{pct}% <span className="font-normal text-zinc-500">({count})</span></span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function PerfTable({ title, rows, columns }) {
  if (rows.length === 0) return null

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900">
      <div className="border-b border-zinc-800 px-5 py-4">
        <h2 className="text-sm font-semibold text-zinc-300">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-zinc-800">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-zinc-500"
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {rows.map((row, i) => (
              <tr key={i} className="hover:bg-zinc-800/40">
                {columns.map((col) => (
                  <td key={col.key} className={`px-4 py-3 ${col.className ?? 'text-zinc-300'}`}>
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default function StatisticsPage() {
  const { t } = useTranslation()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    apiFetch('/api/trades')
      .then((response) => {
        if (!response.ok) throw new Error()
        return response.json()
      })
      .then((data) => setTrades(data.trades ?? []))
      .catch(() => setError(t('common.loadError')))
      .finally(() => setLoading(false))
  }, [t])

  const displayTrades = useMemo(() => tradesWithProfileCurrency(trades, profile), [trades, profile])
  const stats = useMemo(() => buildStatistics(displayTrades), [displayTrades])
  const setupTagStats = useMemo(() => buildSetupTagStats(displayTrades), [displayTrades])
  const dowStats = useMemo(() => buildDayOfWeekStats(displayTrades), [displayTrades])
  const equityCurve = useMemo(() => buildEquityCurve(displayTrades), [displayTrades])
  const drawdown = useMemo(() => buildDrawdown(displayTrades), [displayTrades])
  const disciplineStats = useMemo(() => buildDisciplineStats(displayTrades), [displayTrades])
  const rMultiple = useMemo(() => buildRMultipleStats(displayTrades, profile), [displayTrades, profile])
  const streaks = useMemo(() => buildStreaks(displayTrades), [displayTrades])
  const sessionStats = useMemo(() => buildSessionStats(displayTrades), [displayTrades])
  const monthlyStats = useMemo(() => buildMonthlyStats(displayTrades), [displayTrades])
  const bestSetup = setupTagStats.length > 0
    ? setupTagStats.reduce((best, row) => (row.totalPnl > best.totalPnl ? row : best))
    : null
  const worstSetup = setupTagStats.length > 0
    ? setupTagStats.reduce((worst, row) => (row.totalPnl < worst.totalPnl ? row : worst))
    : null

  if (loading) return <LoadingSpinner center />

  if (error) {
    return (
      <div className="rounded-xl border border-red-900 bg-red-950/40 px-5 py-4 text-sm text-red-300">
        {error}
      </div>
    )
  }

  const setupTagColumns = [
    { key: 'tag', label: t('statistics.tag'), className: 'font-medium text-white' },
    { key: 'count', label: t('statistics.trades'), className: 'text-zinc-300' },
    {
      key: 'winRate',
      label: t('statistics.winRateShort'),
      className: 'text-zinc-300',
      render: (row) => `${row.winRate}%`,
    },
    {
      key: 'avgPnl',
      label: t('statistics.avgPnlShort'),
      render: (row) => (
        <span className={row.avgPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
          {formatCurrency(row.avgPnl, currency)}
        </span>
      ),
    },
    {
      key: 'totalPnl',
      label: t('statistics.totalProfit'),
      render: (row) => (
        <span className={row.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
          {formatCurrency(row.totalPnl, currency)}
        </span>
      ),
    },
  ]

  const dowColumns = [
    { key: 'label', label: t('statistics.day'), className: 'font-medium text-white' },
    { key: 'count', label: t('statistics.trades'), className: 'text-zinc-300' },
    {
      key: 'winRate',
      label: t('statistics.winRateShort'),
      className: 'text-zinc-300',
      render: (row) => `${row.winRate}%`,
    },
    {
      key: 'avgPnl',
      label: t('statistics.avgPnlShort'),
      render: (row) => (
        <span className={row.avgPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
          {formatCurrency(row.avgPnl, currency)}
        </span>
      ),
    },
    {
      key: 'totalPnl',
      label: t('statistics.totalProfit'),
      render: (row) => (
        <span className={row.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
          {formatCurrency(row.totalPnl, currency)}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('statistics.title')}</h1>
        <p className="mt-1 text-sm text-zinc-500">{t('statistics.subtitle')}</p>
      </div>

      {usesIndicativeFx(profile) ? (
        <p className="rounded-lg border border-amber-900/60 bg-amber-950/20 px-4 py-2 text-xs text-amber-300">
          {t('dashboard.indicativeFx')}
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatItem label={t('statistics.totalTrades')} value={stats.totalTrades} />
        <StatItem label={t('statistics.winRate')} value={`${stats.winRate}%`} />
        <StatItem label={t('statistics.profitableTrades')} value={stats.winningTrades} />
        <StatItem label={t('statistics.losingTrades')} value={stats.losingTrades} />

        <StatItem
          label={t('statistics.totalProfit')}
          value={formatCurrency(stats.totalProfitLoss, currency)}
          className={stats.totalProfitLoss >= 0 ? 'text-emerald-400' : 'text-red-400'}
        />
        <StatItem label={t('statistics.averageWin')} value={formatCurrency(stats.avgWin, currency)} className="text-emerald-400" />
        <StatItem label={t('statistics.averageLoss')} value={formatCurrency(stats.avgLoss, currency)} className="text-red-400" />
        <StatItem
          label={t('statistics.profitFactor')}
          value={stats.profitFactor === null ? '-' : stats.profitFactor.toFixed(2)}
        />
        <StatItem
          label={t('statistics.equityPeak')}
          value={formatCurrency(drawdown.equityPeak, currency)}
        />
        <StatItem
          label={t('statistics.lowestAfterPeak')}
          value={formatCurrency(drawdown.lowestEquityAfterPeak, currency)}
          className={drawdown.lowestEquityAfterPeak < drawdown.equityPeak ? 'text-red-400' : 'text-white'}
        />

        <StatItem label={t('statistics.buyCount')} value={stats.buyCount} />
        <StatItem label={t('statistics.sellCount')} value={stats.sellCount} />

        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">{t('statistics.bestSetup')}</p>
          <p className={bestSetup ? 'mt-2 text-sm text-emerald-400' : 'mt-2 text-sm text-zinc-500'}>
            {bestSetup ? `${bestSetup.tag} - ${formatCurrency(bestSetup.totalPnl, currency)}` : '-'}
          </p>
        </div>

        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">{t('statistics.worstSetup')}</p>
          <p className={worstSetup ? 'mt-2 text-sm text-red-400' : 'mt-2 text-sm text-zinc-500'}>
            {worstSetup ? `${worstSetup.tag} - ${formatCurrency(worstSetup.totalPnl, currency)}` : '-'}
          </p>
        </div>

        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">{t('statistics.bestTrade')}</p>
          {stats.bestTrade ? (
            <Link href={`/trades/${stats.bestTrade.id}`} className="mt-2 block text-sm text-emerald-400 hover:underline">
              {stats.bestTrade.symbol} • {formatCurrency(stats.bestTrade.profitLoss, currency)} • {formatDate(stats.bestTrade.date)}
            </Link>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">-</p>
          )}
        </div>

        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">{t('statistics.worstTrade')}</p>
          {stats.worstTrade ? (
            <Link href={`/trades/${stats.worstTrade.id}`} className="mt-2 block text-sm text-red-400 hover:underline">
              {stats.worstTrade.symbol} • {formatCurrency(stats.worstTrade.profitLoss, currency)} • {formatDate(stats.worstTrade.date)}
            </Link>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">-</p>
          )}
        </div>

        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">{t('statistics.bestDay')}</p>
          {stats.bestDay ? (
            <p className="mt-2 text-sm text-emerald-400">
              {formatDate(stats.bestDay.date)} • {formatCurrency(stats.bestDay.pnl, currency)}
            </p>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">-</p>
          )}
        </div>

        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <p className="text-xs uppercase tracking-wider text-zinc-500">{t('statistics.worstDay')}</p>
          {stats.worstDay ? (
            <p className="mt-2 text-sm text-red-400">
              {formatDate(stats.worstDay.date)} • {formatCurrency(stats.worstDay.pnl, currency)}
            </p>
          ) : (
            <p className="mt-2 text-sm text-zinc-500">-</p>
          )}
        </div>
      </div>

      <PerfTable
        title={t('statistics.setupTagPerformance')}
        rows={setupTagStats}
        columns={setupTagColumns}
      />

      <PerfTable
        title={t('statistics.dayOfWeek')}
        rows={dowStats}
        columns={dowColumns}
      />

      {/* Equity curve */}
      {equityCurve.length > 1 && (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="mb-4 text-sm font-semibold text-zinc-300">{t('statistics.equityCurve')}</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={equityCurve} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: '#71717a' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(d) => d.slice(5)}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#71717a' }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) => formatCurrency(v, currency)}
                width={72}
              />
              <Tooltip
                contentStyle={{ background: '#18181b', border: '1px solid #27272a', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#a1a1aa' }}
                formatter={(value) => [formatCurrency(value, currency), t('statistics.equityCurve')]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: '#10b981' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </section>
      )}

      {/* Drawdown */}
      <div className="grid grid-cols-2 gap-4">
        <StatItem
          label={t('statistics.currentDrawdown')}
          value={drawdown.currentDrawdown > 0 ? formatCurrency(-drawdown.currentDrawdown, currency) : '-'}
          className={drawdown.currentDrawdown > 0 ? 'text-red-400' : 'text-white'}
        />
        <StatItem
          label={t('statistics.maxDrawdown')}
          value={drawdown.maxDrawdown > 0 ? formatCurrency(-drawdown.maxDrawdown, currency) : '-'}
          className={drawdown.maxDrawdown > 0 ? 'text-red-400' : 'text-white'}
        />
      </div>

      {/* Discipline stats */}
      {disciplineStats.total > 0 && (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-zinc-300">{t('statistics.disciplineStats')}</h2>
            <span className={`text-2xl font-bold ${disciplineStats.goodPct >= 70 ? 'text-emerald-400' : disciplineStats.goodPct >= 50 ? 'text-amber-400' : 'text-red-400'}`}>
              {disciplineStats.goodPct}%
            </span>
          </div>
          <p className="mb-4 text-xs text-zinc-500">
            {t('statistics.disciplineRated', { count: disciplineStats.total })}
          </p>
          <div className="space-y-3">
            <DisciplineBar label={`😄🙂 ${t('statistics.goodTrades')}`} pct={disciplineStats.goodPct} count={disciplineStats.good} color="bg-emerald-500" />
            <DisciplineBar label={`😐 ${t('statistics.neutralTrades')}`} pct={disciplineStats.neutralPct} count={disciplineStats.neutral} color="bg-amber-500" />
            <DisciplineBar label={`😞😡 ${t('statistics.badTrades')}`} pct={disciplineStats.badPct} count={disciplineStats.bad} color="bg-red-500" />
          </div>
        </section>
      )}

      {/* R-Multiple */}
      {rMultiple.count > 0 && (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="mb-4 text-sm font-semibold text-zinc-300">{t('statistics.rSection')}</h2>
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <StatItem
              label={t('statistics.avgR')}
              value={`${rMultiple.avgR.toFixed(2)}R`}
              className={rMultiple.avgR >= 0 ? 'text-emerald-400' : 'text-red-400'}
            />
            <StatItem
              label={t('statistics.bestR')}
              value={`${rMultiple.bestR.toFixed(2)}R`}
              className="text-emerald-400"
            />
            <StatItem
              label={t('statistics.worstR')}
              value={`${rMultiple.worstR.toFixed(2)}R`}
              className="text-red-400"
            />
            <StatItem label={t('statistics.rTrades')} value={rMultiple.count} />
          </div>
        </section>
      )}

      {/* Streaks */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="mb-4 text-sm font-semibold text-zinc-300">{t('statistics.streaks')}</h2>
        <div className="grid grid-cols-2 gap-4">
          <StatItem
            label={t('statistics.currentWinStreak')}
            value={streaks.currentWinStreak}
            className={streaks.currentWinStreak > 0 ? 'text-emerald-400' : 'text-white'}
          />
          <StatItem
            label={t('statistics.currentLossStreak')}
            value={streaks.currentLossStreak}
            className={streaks.currentLossStreak > 0 ? 'text-red-400' : 'text-white'}
          />
          <StatItem label={t('statistics.longestWinStreak')} value={streaks.longestWinStreak} />
          <StatItem label={t('statistics.longestLossStreak')} value={streaks.longestLossStreak} />
        </div>
      </section>

      {/* Session performance */}
      <PerfTable
        title={t('statistics.sessions')}
        rows={sessionStats}
        columns={[
          { key: 'session', label: t('statistics.session'), className: 'font-medium text-white' },
          { key: 'count', label: t('statistics.trades'), className: 'text-zinc-300' },
          { key: 'winRate', label: t('statistics.winRateShort'), className: 'text-zinc-300', render: (row) => `${row.winRate}%` },
          {
            key: 'avgPnl',
            label: t('statistics.avgPnlShort'),
            render: (row) => (
              <span className={row.avgPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {formatCurrency(row.avgPnl, currency)}
              </span>
            ),
          },
          {
            key: 'totalPnl',
            label: t('statistics.totalProfit'),
            render: (row) => (
              <span className={row.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {formatCurrency(row.totalPnl, currency)}
              </span>
            ),
          },
        ]}
      />

      {/* Monthly performance */}
      <PerfTable
        title={t('statistics.monthly')}
        rows={monthlyStats}
        columns={[
          {
            key: 'month',
            label: t('statistics.month'),
            className: 'font-medium text-white whitespace-nowrap',
            render: (row) => {
              const [y, m] = row.month.split('-')
              return new Date(Number(y), Number(m) - 1, 1).toLocaleDateString('en-US', { year: 'numeric', month: 'short' })
            },
          },
          { key: 'count', label: t('statistics.trades'), className: 'text-zinc-300' },
          { key: 'winRate', label: t('statistics.winRateShort'), className: 'text-zinc-300', render: (row) => `${row.winRate}%` },
          {
            key: 'totalPnl',
            label: t('statistics.totalProfit'),
            render: (row) => (
              <span className={row.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                {formatCurrency(row.totalPnl, currency)}
              </span>
            ),
          },
          {
            key: 'bestPnl',
            label: t('statistics.bestTrade'),
            render: (row) => <span className="text-emerald-400">{formatCurrency(row.bestPnl, currency)}</span>,
          },
          {
            key: 'worstPnl',
            label: t('statistics.worstTrade'),
            render: (row) => <span className="text-red-400">{formatCurrency(row.worstPnl, currency)}</span>,
          },
          {
            key: 'maxDrawdown',
            label: t('statistics.maxDrawdown'),
            render: (row) => (
              <span className={row.maxDrawdown > 0 ? 'text-red-400' : 'text-zinc-500'}>
                {row.maxDrawdown > 0 ? formatCurrency(-row.maxDrawdown, currency) : '-'}
              </span>
            ),
          },
        ]}
      />
    </div>
  )
}
