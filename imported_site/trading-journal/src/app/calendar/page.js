'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useProfile } from '@/components/ProfileProvider'
import { formatCurrency, getStatusLabelKey, tradesWithProfileCurrency } from '@/lib/tradeUtils'
import { pnlColor, typeBadgeClass } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

function getDaysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate()
}

function getFirstDowMonBased(year, month) {
  const dayOfWeek = new Date(year, month, 1).getDay()
  return (dayOfWeek + 6) % 7
}

function toDateKey(year, month, day) {
  const monthText = String(month + 1).padStart(2, '0')
  const dayText = String(day).padStart(2, '0')
  return `${year}-${monthText}-${dayText}`
}

const WEEK_DAY_LABELS = Array.from({ length: 7 }, (_, index) => {
  const date = new Date(2024, 0, 1 + index)
  return date.toLocaleDateString(undefined, { weekday: 'short' })
})

export default function CalendarPage() {
  const { t } = useTranslation()
  const searchParams = useSearchParams()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'

  const today = new Date()
  const initialQueryDate = searchParams.get('date')

  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth())
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedDate, setSelectedDate] = useState(initialQueryDate)
  const displayTrades = useMemo(() => tradesWithProfileCurrency(trades, profile), [trades, profile])

  const dateFrom = toDateKey(year, month, 1)
  const dateTo = toDateKey(year, month, getDaysInMonth(year, month))

  useEffect(() => {
    let active = true

    fetch(`/api/trades?dateFrom=${dateFrom}&dateTo=${dateTo}&sortBy=date-asc`)
      .then((response) => response.json())
      .then((data) => {
        if (!active) return
        setTrades(data.trades ?? [])
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })

    return () => {
      active = false
    }
  }, [dateFrom, dateTo, initialQueryDate])

  const tradesByDate = useMemo(() => {
    const map = {}

    for (const trade of displayTrades) {
      if (!map[trade.date]) map[trade.date] = []
      map[trade.date].push(trade)
    }

    return map
  }, [displayTrades])

  const selectedTrades = selectedDate ? tradesByDate[selectedDate] ?? [] : []
  const monthPnl = displayTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)
  const tradingDays = Object.keys(tradesByDate).length

  function prevMonth() {
    setLoading(true)

    if (month === 0) {
      setYear((currentYear) => currentYear - 1)
      setMonth(11)
      return
    }

    setMonth((currentMonth) => currentMonth - 1)
  }

  function nextMonth() {
    setLoading(true)

    if (month === 11) {
      setYear((currentYear) => currentYear + 1)
      setMonth(0)
      return
    }

    setMonth((currentMonth) => currentMonth + 1)
  }

  const daysInMonth = getDaysInMonth(year, month)
  const padStart = getFirstDowMonBased(year, month)
  const todayKey = toDateKey(today.getFullYear(), today.getMonth(), today.getDate())

  const monthLabel = new Date(year, month, 1).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('calendar.title')}</h1>
          <p className="mt-1 text-sm text-zinc-500">{t('calendar.subtitle')}</p>
        </div>

        <Link
          href="/trades/new"
          className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-500"
        >
          {t('dashboard.newTrade')}
        </Link>
      </div>

      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
        <div className="mb-4 flex items-center justify-between">
          <button
            onClick={prevMonth}
            className="rounded-lg px-3 py-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
            aria-label={t('calendar.prevMonth')}
          >
            {'<'}
          </button>

          <h2 className="font-semibold capitalize text-white">{monthLabel}</h2>

          <button
            onClick={nextMonth}
            className="rounded-lg px-3 py-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
            aria-label={t('calendar.nextMonth')}
          >
            {'>'}
          </button>
        </div>

        <div className="mb-1 grid grid-cols-7 gap-1">
          {WEEK_DAY_LABELS.map((label) => (
            <div key={label} className="py-1 text-center text-xs font-semibold uppercase tracking-wide text-zinc-500">
              {label}
            </div>
          ))}
        </div>

        {loading ? (
          <div className="flex h-48 items-center justify-center">
            <LoadingSpinner />
          </div>
        ) : (
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: padStart }).map((_, index) => (
              <div key={`pad-${index}`} />
            ))}

            {Array.from({ length: daysInMonth }).map((_, index) => {
              const day = index + 1
              const key = toDateKey(year, month, day)
              const dayTrades = tradesByDate[key] ?? []
              const isToday = key === todayKey
              const isSelected = key === selectedDate
              const hasTrades = dayTrades.length > 0
              const dayPnl = dayTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)

              return (
                <button
                  key={key}
                  onClick={() => setSelectedDate(isSelected ? null : key)}
                  className={[
                    'flex flex-col items-center rounded-lg py-2 text-sm transition-colors',
                    isSelected
                      ? 'bg-emerald-600 text-white'
                      : isToday
                        ? 'border border-emerald-600/60 text-white hover:bg-zinc-800'
                        : hasTrades
                          ? 'text-white hover:bg-zinc-800'
                          : 'text-zinc-600 hover:bg-zinc-800 hover:text-zinc-300',
                  ].join(' ')}
                >
                  <span className={['text-sm font-medium', isToday && !isSelected ? 'text-emerald-400' : ''].join(' ')}>
                    {day}
                  </span>

                  {hasTrades ? (
                    <>
                      <span
                        className={[
                          'mt-0.5 text-xs font-bold leading-none',
                          isSelected ? 'text-white/80' : dayPnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                        ].join(' ')}
                      >
                        {dayTrades.length}
                      </span>

                      <span
                        className={[
                          'mt-0.5 hidden text-xs leading-none sm:block',
                          isSelected ? 'text-white/70' : dayPnl >= 0 ? 'text-emerald-400' : 'text-red-400',
                        ].join(' ')}
                      >
                        {dayPnl >= 0 ? '+' : ''}
                        {dayPnl.toFixed(0)}
                      </span>
                    </>
                  ) : null}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {!loading && trades.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
            <p className="text-xs uppercase tracking-wider text-zinc-500">{t('calendar.monthTrades')}</p>
            <p className="mt-1 text-2xl font-bold text-white">{trades.length}</p>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
            <p className="text-xs uppercase tracking-wider text-zinc-500">{t('calendar.tradingDays')}</p>
            <p className="mt-1 text-2xl font-bold text-white">{tradingDays}</p>
          </div>

          <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900 p-4 sm:col-span-1">
            <p className="text-xs uppercase tracking-wider text-zinc-500">{t('calendar.monthPnl')}</p>
            <p className={`mt-1 text-2xl font-bold ${monthPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {formatCurrency(monthPnl, currency)}
            </p>
          </div>
        </div>
      ) : null}

      {selectedDate ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900">
          <div className="border-b border-zinc-800 px-5 py-4">
            <h2 className="text-sm font-semibold text-zinc-300">
              {t('calendar.tradesOn')}{' '}
              {new Date(`${selectedDate}T00:00:00`).toLocaleDateString(undefined, {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric',
              })}
            </h2>
          </div>

          {selectedTrades.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-zinc-500">{t('calendar.noTrades')}</p>
          ) : (
            <div className="divide-y divide-zinc-800">
              {selectedTrades.map((trade) => (
                <Link
                  key={trade.id}
                  href={`/trades/${trade.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 transition-colors hover:bg-zinc-800/40"
                >
                  <div className="flex items-center gap-3">
                    <span className={`rounded px-2 py-0.5 text-xs font-semibold ${typeBadgeClass(trade.tradeType)}`}>
                      {trade.tradeType === 'Buy' ? t('trades.buy') : t('trades.sell')}
                    </span>
                    <span className="text-sm font-medium text-white">{trade.symbol}</span>
                    <span className="text-xs text-zinc-500">
                      {t('calendar.entry')}: {trade.entryPrice}
                    </span>
                    <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">
                      {t(getStatusLabelKey(trade.status))}
                    </span>
                    {trade.satisfactionEmoji ? <span className="text-base leading-none">{trade.satisfactionEmoji}</span> : null}
                  </div>

                  <p className={`text-sm font-semibold ${pnlColor(trade.profitLoss)}`}>
                    {formatCurrency(trade.profitLoss, currency)}
                  </p>
                </Link>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  )
}
