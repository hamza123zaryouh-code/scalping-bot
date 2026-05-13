'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import ConfirmModal from '@/components/ConfirmModal'
import EmptyState from '@/components/EmptyState'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useToast } from '@/components/ToastProvider'
import { useProfile } from '@/components/ProfileProvider'
import { apiFetch } from '@/lib/apiFetch'
import {
  SATISFACTION_EMOJIS,
  SETUP_TAGS,
  TRADE_STATUSES,
  formatCurrency,
  getStatusLabelKey,
  tradesWithProfileCurrency,
} from '@/lib/tradeUtils'
import { useTranslation } from '@/lib/i18n'
import { formatDate, pnlColor, typeBadgeClass } from '@/lib/utils'

const DEFAULT_FILTERS = {
  search: '',
  type: '',
  status: '',
  result: '',
  satisfactionEmoji: '',
  setupTag: '',
  marker: '',
  date: '',
  sortBy: 'date-desc',
}

const inputClass =
  'w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-white focus:border-emerald-600 focus:outline-none'

export default function TradesPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const searchParams = useSearchParams()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'

  const initialMarker = searchParams.get('marker') ?? ''
  const [trades, setTrades] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState(() => ({ ...DEFAULT_FILTERS, marker: initialMarker }))
  const [deleteTradeId, setDeleteTradeId] = useState('')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const displayTrades = useMemo(() => tradesWithProfileCurrency(trades, profile), [trades, profile])

  async function fetchTrades(nextFilters = filters) {
    setLoading(true)
    const params = new URLSearchParams()
    Object.entries(nextFilters).forEach(([key, value]) => {
      if (value) params.set(key, value)
    })
    try {
      const response = await apiFetch(`/api/trades?${params.toString()}`)
      const data = await response.json()
      if (!response.ok) {
        toast(data.error || t('trades.fetchError'), 'error')
        setTrades([])
      } else {
        setTrades(data.trades ?? [])
      }
    } catch {
      toast(t('trades.fetchError'), 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    const initialFilters = { ...DEFAULT_FILTERS, marker: initialMarker }
    const params = new URLSearchParams()
    Object.entries(initialFilters).forEach(([key, value]) => {
      if (value) params.set(key, value)
    })

    apiFetch(`/api/trades?${params.toString()}`)
      .then((response) =>
        response.json().then((data) => ({
          ok: response.ok,
          data,
        }))
      )
      .then(({ ok, data }) => {
        if (!active) return

        if (!ok) {
          toast(data.error || t('trades.fetchError'), 'error')
          setTrades([])
          return
        }

        setTrades(data.trades ?? [])
      })
      .catch(() => {
        if (active) {
          toast(t('trades.fetchError'), 'error')
        }
      })
      .finally(() => { if (active) setLoading(false) })

    return () => { active = false }
  }, [initialMarker, t, toast])

  function updateFilter(key, value) {
    const nextFilters = { ...filters, [key]: value }
    setFilters(nextFilters)
    fetchTrades(nextFilters)
  }

  async function handleDelete() {
    if (!deleteTradeId) return

    const response = await fetch(`/api/trades/${deleteTradeId}`, { method: 'DELETE' })
    const data = await response.json()

    setDeleteTradeId('')

    if (!response.ok) {
      toast(data.error || t('trades.deleteFailed'), 'error')
      return
    }

    toast(t('trades.deleteSuccess'))
    fetchTrades()
  }

  const filterBar = (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <input
        value={filters.search}
        onChange={(event) => updateFilter('search', event.target.value)}
        placeholder={t('trades.searchPlaceholder')}
        className={`${inputClass} sm:col-span-2 xl:col-span-2`}
      />

      <select
        value={filters.type}
        onChange={(event) => updateFilter('type', event.target.value)}
        className={inputClass}
      >
        <option value="">{t('trades.allTypes')}</option>
        <option value="Buy">{t('trades.buy')}</option>
        <option value="Sell">{t('trades.sell')}</option>
      </select>

      <select
        value={filters.status}
        onChange={(event) => updateFilter('status', event.target.value)}
        className={inputClass}
      >
        <option value="">{t('trades.allStatuses')}</option>
        {TRADE_STATUSES.map((status) => (
          <option key={status} value={status}>
            {t(getStatusLabelKey(status))}
          </option>
        ))}
      </select>

      <select
        value={filters.result}
        onChange={(event) => updateFilter('result', event.target.value)}
        className={inputClass}
      >
        <option value="">{t('trades.allResults')}</option>
        <option value="profit">{t('trades.profitOnly')}</option>
        <option value="loss">{t('trades.lossOnly')}</option>
      </select>

      <select
        value={filters.satisfactionEmoji}
        onChange={(event) => updateFilter('satisfactionEmoji', event.target.value)}
        className={inputClass}
      >
        <option value="">{t('trades.allSatisfaction')}</option>
        {SATISFACTION_EMOJIS.map((emoji) => (
          <option key={emoji} value={emoji}>
            {emoji}
          </option>
        ))}
      </select>

      <select
        value={filters.setupTag}
        onChange={(event) => updateFilter('setupTag', event.target.value)}
        className={inputClass}
      >
        <option value="">{t('trades.allSetupTags')}</option>
        {SETUP_TAGS.map((tag) => (
          <option key={tag} value={tag}>
            {tag}
          </option>
        ))}
      </select>

      <select
        value={filters.marker}
        onChange={(event) => updateFilter('marker', event.target.value)}
        className={inputClass}
      >
        <option value="">{t('trades.allMarkers')}</option>
        <option value="favorite">{t('trades.favoritesOnly')}</option>
        <option value="mistake">{t('trades.mistakesOnly')}</option>
      </select>

      <input
        type="date"
        value={filters.date}
        onChange={(event) => updateFilter('date', event.target.value)}
        className={inputClass}
      />

      <select
        value={filters.sortBy}
        onChange={(event) => updateFilter('sortBy', event.target.value)}
        className={inputClass}
      >
        <option value="date-desc">{t('trades.sortDateDesc')}</option>
        <option value="date-asc">{t('trades.sortDateAsc')}</option>
        <option value="result-desc">{t('trades.sortPnlDesc')}</option>
        <option value="result-asc">{t('trades.sortPnlAsc')}</option>
      </select>

      <button
        onClick={() => {
          setFilters(DEFAULT_FILTERS)
          fetchTrades(DEFAULT_FILTERS)
        }}
        className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-400 transition-colors hover:text-white"
      >
        {t('trades.clearFilters')}
      </button>
    </div>
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('trades.title')}</h1>
          <p className="text-sm text-zinc-500">{t('trades.count', { count: trades.length })}</p>
        </div>

        <div className="flex gap-2">
          <Link
            href="/trades/new"
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-500"
          >
            {t('trades.newTrade')}
          </Link>
        </div>
      </div>

      {/* Desktop filters */}
      <div className="hidden rounded-xl border border-zinc-800 bg-zinc-900 p-4 md:block">
        {filterBar}
      </div>

      {/* Mobile collapsible filters */}
      {(() => {
        const activeCount = Object.entries(filters).filter(
          ([k, v]) => k !== 'sortBy' && v !== '' && v !== DEFAULT_FILTERS[k]
        ).length
        return (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900 md:hidden">
            <button
              onClick={() => setFiltersOpen((prev) => !prev)}
              className="flex w-full items-center justify-between px-4 py-3.5 text-sm text-zinc-300"
            >
              <span className="flex items-center gap-2">
                <svg className="h-4 w-4 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                </svg>
                {t('trades.filters')}
                {activeCount > 0 && (
                  <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white">
                    {activeCount}
                  </span>
                )}
              </span>
              <svg
                className={`h-4 w-4 text-zinc-500 transition-transform ${filtersOpen ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {filtersOpen && (
              <div className="border-t border-zinc-800 p-4">
                {filterBar}
              </div>
            )}
          </div>
        )
      })()}

      {loading ? (
        <LoadingSpinner center />
      ) : trades.length === 0 ? (
        <EmptyState
          title={t('trades.emptyTitle')}
          message={t('trades.emptyMessage')}
          action={{ href: '/trades/new', label: t('trades.emptyAction') }}
        />
      ) : (
        <>
          {/* Mobile trade cards */}
          <div className="space-y-2 md:hidden">
            {displayTrades.map((trade) => (
              <Link
                key={trade.id}
                href={`/trades/${trade.id}`}
                className="block rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-4 transition-colors active:bg-zinc-800/80"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${typeBadgeClass(trade.tradeType)}`}>
                        {trade.tradeType === 'Buy' ? t('trades.buy') : t('trades.sell')}
                      </span>
                      <span className="text-sm font-bold text-white">{trade.symbol}</span>
                      {trade.satisfactionEmoji && (
                        <span className="text-base leading-none">{trade.satisfactionEmoji}</span>
                      )}
                      {trade.isFavorite && (
                        <span className="text-xs text-amber-400">★</span>
                      )}
                      {trade.isMistake && (
                        <span className="text-xs text-red-400">⚠</span>
                      )}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-500">
                      <span>{formatDate(trade.date)}</span>
                      <span>·</span>
                      <span>{t(getStatusLabelKey(trade.status))}</span>
                      {trade.setupTag && (
                        <>
                          <span>·</span>
                          <span className="text-zinc-400">{trade.setupTag}</span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={`text-base font-bold tabular-nums ${pnlColor(trade.profitLoss)}`}>
                      {formatCurrency(trade.profitLoss, currency)}
                    </p>
                    <p className="mt-0.5 text-xs tabular-nums text-zinc-600">
                      {t('trades.entry')}: {trade.entryPrice}
                    </p>
                  </div>
                </div>
              </Link>
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden overflow-x-auto rounded-xl border border-zinc-800 md:block">
            <table className="w-full text-sm">
              <thead className="border-b border-zinc-800 bg-zinc-900">
                <tr>
                  {[
                    t('trades.date'),
                    t('trades.symbol'),
                    t('trades.type'),
                    t('trades.entry'),
                    t('trades.lotSize'),
                    t('trades.status'),
                    t('trades.result'),
                    t('trades.satisfaction'),
                    t('trades.setupTag'),
                    '',
                  ].map((header, i) => (
                    <th
                      key={i}
                      className="whitespace-nowrap px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-zinc-500"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody className="divide-y divide-zinc-800">
                {displayTrades.map((trade) => (
                  <tr key={trade.id} className="transition-colors hover:bg-zinc-800/40">
                    <td className="whitespace-nowrap px-4 py-3 text-zinc-400">{formatDate(trade.date)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-white">{trade.symbol}</span>
                        {trade.isFavorite && <span title={t('trades.favoriteBadge')} className="text-amber-300 text-xs">★</span>}
                        {trade.isMistake && <span title={t('trades.mistakeBadge')} className="text-red-300 text-xs">⚠</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${typeBadgeClass(trade.tradeType)}`}>
                        {trade.tradeType === 'Buy' ? t('trades.buy') : t('trades.sell')}
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums text-zinc-300">{trade.entryPrice}</td>
                    <td className="px-4 py-3 tabular-nums text-zinc-300">{trade.lotSize}</td>
                    <td className="px-4 py-3 text-zinc-400">{t(getStatusLabelKey(trade.status))}</td>
                    <td className={`px-4 py-3 font-semibold tabular-nums ${pnlColor(trade.profitLoss)}`}>
                      {formatCurrency(trade.profitLoss, currency)}
                    </td>
                    <td className="px-4 py-3 text-center text-lg leading-none">
                      {trade.satisfactionEmoji ?? <span className="text-zinc-700">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {trade.setupTag ? (
                        <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-300">
                          {trade.setupTag}
                        </span>
                      ) : (
                        <span className="text-zinc-700">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-3">
                        <Link
                          href={`/trades/${trade.id}`}
                          className="text-xs text-zinc-400 transition-colors hover:text-white"
                        >
                          {t('trades.view')}
                        </Link>
                        <Link
                          href={`/trades/${trade.id}/edit`}
                          className="text-xs text-zinc-400 transition-colors hover:text-emerald-400"
                        >
                          {t('trades.edit')}
                        </Link>
                        <button
                          onClick={() => setDeleteTradeId(trade.id)}
                          className="text-xs text-zinc-400 transition-colors hover:text-red-400"
                        >
                          {t('trades.delete')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <ConfirmModal
        isOpen={Boolean(deleteTradeId)}
        title={t('trades.deleteTitle')}
        message={t('trades.deleteMessage')}
        cancelLabel={t('common.cancel')}
        confirmLabel={t('common.confirm')}
        onCancel={() => setDeleteTradeId('')}
        onConfirm={handleDelete}
      />
    </div>
  )
}
