'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useToast } from '@/components/ToastProvider'
import { useTranslation } from '@/lib/i18n'
import { useProfile } from '@/components/ProfileProvider'
import { buildTradeMarkerStats, formatCurrency, tradesWithProfileCurrency } from '@/lib/tradeUtils'
import { formatDate } from '@/lib/utils'

function getMonday(date = new Date()) {
  const value = new Date(date)
  const day = value.getDay()
  const diff = day === 0 ? -6 : 1 - day
  value.setDate(value.getDate() + diff)
  return value.toISOString().slice(0, 10)
}

const DEFAULT_FORM = {
  weekStart: getMonday(),
  wentWell: '',
  wentWrong: '',
  improveNextWeek: '',
}

const inputClass =
  'w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:border-emerald-600 focus:outline-none'

export default function ReviewsPage() {
  const toast = useToast()
  const { t } = useTranslation()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [reviews, setReviews] = useState([])
  const [trades, setTrades] = useState([])
  const [form, setForm] = useState(DEFAULT_FORM)
  const defaultWeekStart = DEFAULT_FORM.weekStart

  async function fetchReviews() {
    const response = await fetch('/api/reviews')
    const data = await response.json()

    if (!response.ok) {
      toast(data.error || t('reviews.fetchError'), 'error')
      return
    }

    if (data.warning) {
      toast(data.warning, 'info')
    }

    const nextReviews = data.reviews ?? []
    setReviews(nextReviews)

    const existing = nextReviews.find((review) => review.weekStart === form.weekStart)
    if (existing) {
      setForm({
        weekStart: existing.weekStart,
        wentWell: existing.wentWell || '',
        wentWrong: existing.wentWrong || '',
        improveNextWeek: existing.improveNextWeek || '',
      })
    }
  }

  useEffect(() => {
    let active = true

    Promise.all([
      fetch('/api/reviews').then((response) => response.json().then((data) => ({ ok: response.ok, data }))),
      fetch('/api/trades?sortBy=date-desc').then((response) => response.json().then((data) => ({ ok: response.ok, data }))),
    ])
      .then(([reviewsResult, tradesResult]) => {
        if (!active) return

        if (!reviewsResult.ok) {
          toast(reviewsResult.data.error || t('reviews.fetchError'), 'error')
          return
        }

        if (reviewsResult.data.warning) {
          toast(reviewsResult.data.warning, 'info')
        }

        const nextReviews = reviewsResult.data.reviews ?? []
        setReviews(nextReviews)
        setTrades(tradesResult.ok ? tradesResult.data.trades ?? [] : [])

        const existing = nextReviews.find((review) => review.weekStart === defaultWeekStart)
        if (existing) {
          setForm({
            weekStart: existing.weekStart,
            wentWell: existing.wentWell || '',
            wentWrong: existing.wentWrong || '',
            improveNextWeek: existing.improveNextWeek || '',
          })
        }
      })
      .finally(() => {
        if (!active) return
        setLoading(false)
      })

    return () => {
      active = false
    }
  }, [defaultWeekStart, t, toast])

  const reviewForSelectedWeek = useMemo(
    () => reviews.find((review) => review.weekStart === form.weekStart) || null,
    [form.weekStart, reviews]
  )
  const displayTrades = useMemo(() => tradesWithProfileCurrency(trades, profile), [trades, profile])
  const markerStats = useMemo(() => buildTradeMarkerStats(displayTrades), [displayTrades])

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function loadReviewForWeek(weekStart) {
    const existing = reviews.find((review) => review.weekStart === weekStart)

    setForm({
      weekStart,
      wentWell: existing?.wentWell || '',
      wentWrong: existing?.wentWrong || '',
      improveNextWeek: existing?.improveNextWeek || '',
    })
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)

    const response = await fetch('/api/reviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })

    const data = await response.json()
    setSaving(false)

    if (!response.ok) {
      toast(data.error || t('reviews.saveError'), 'error')
      return
    }

    toast(t('reviews.saved'))
    fetchReviews()
  }

  async function handleDelete(id) {
    const response = await fetch(`/api/reviews/${id}`, { method: 'DELETE' })
    const data = await response.json()

    if (!response.ok) {
      toast(data.error || t('reviews.deleteError'), 'error')
      return
    }

    toast(t('reviews.deleted'))
    fetchReviews()
  }

  if (loading) return <LoadingSpinner center />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('reviews.title')}</h1>
        <p className="mt-1 text-sm text-zinc-500">{t('reviews.subtitle')}</p>
      </div>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Link href="/trades?marker=favorite" className="rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 transition-colors hover:bg-amber-950/30">
          <p className="text-xs uppercase tracking-widest text-amber-300">{t('reviews.favoriteTrades')}</p>
          <p className="mt-1 text-2xl font-bold text-white">{markerStats.favoriteCount}</p>
          <p className={markerStats.favoritePnl >= 0 ? 'text-sm text-emerald-400' : 'text-sm text-red-400'}>
            {formatCurrency(markerStats.favoritePnl, currency)}
          </p>
        </Link>

        <Link href="/trades?marker=mistake" className="rounded-xl border border-red-900/50 bg-red-950/20 p-4 transition-colors hover:bg-red-950/30">
          <p className="text-xs uppercase tracking-widest text-red-300">{t('reviews.mistakeTrades')}</p>
          <p className="mt-1 text-2xl font-bold text-white">{markerStats.mistakeCount}</p>
          <p className={markerStats.mistakePnl >= 0 ? 'text-sm text-emerald-400' : 'text-sm text-red-400'}>
            {formatCurrency(markerStats.mistakePnl, currency)}
          </p>
        </Link>
      </section>

      <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-400">{t('reviews.weekStart')}</span>
          <input
            type="date"
            value={form.weekStart}
            onChange={(event) => loadReviewForWeek(event.target.value)}
            className={inputClass}
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-400">{t('reviews.wentWell')}</span>
          <textarea
            rows={3}
            value={form.wentWell}
            onChange={(event) => updateField('wentWell', event.target.value)}
            className={`${inputClass} resize-none`}
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-400">{t('reviews.wentWrong')}</span>
          <textarea
            rows={3}
            value={form.wentWrong}
            onChange={(event) => updateField('wentWrong', event.target.value)}
            className={`${inputClass} resize-none`}
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-zinc-400">{t('reviews.improveNextWeek')}</span>
          <textarea
            rows={3}
            value={form.improveNextWeek}
            onChange={(event) => updateField('improveNextWeek', event.target.value)}
            className={`${inputClass} resize-none`}
          />
        </label>

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-lg bg-emerald-600 py-3 text-sm font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-60"
        >
          {saving ? t('reviews.saving') : reviewForSelectedWeek ? t('reviews.update') : t('reviews.save')}
        </button>
      </form>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900">
        <div className="border-b border-zinc-800 px-5 py-4">
          <h2 className="text-sm font-semibold text-zinc-300">{t('reviews.history')}</h2>
        </div>

        {reviews.length === 0 ? (
          <div className="px-5 py-8">
            <p className="text-sm text-zinc-500">{t('reviews.empty')}</p>
            <p className="mt-1 text-xs text-zinc-600">{t('reviews.emptyHint')}</p>
          </div>
        ) : (
          <div className="divide-y divide-zinc-800">
            {reviews.map((review) => (
              <article key={review.id} className="space-y-3 px-5 py-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-white">
                    {t('reviews.weekOf')} {formatDate(review.weekStart)}
                  </p>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      onClick={() => loadReviewForWeek(review.weekStart)}
                      className="text-xs text-zinc-400 transition-colors hover:text-emerald-400"
                    >
                      {t('reviews.edit')}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(review.id)}
                      className="text-xs text-zinc-400 transition-colors hover:text-red-400"
                    >
                      {t('reviews.delete')}
                    </button>
                  </div>
                </div>

                {review.wentWell ? (
                  <p className="text-sm text-zinc-300">
                    <span className="text-zinc-500">{t('reviews.wentWell')}: </span>
                    {review.wentWell}
                  </p>
                ) : null}

                {review.wentWrong ? (
                  <p className="text-sm text-zinc-300">
                    <span className="text-zinc-500">{t('reviews.wentWrong')}: </span>
                    {review.wentWrong}
                  </p>
                ) : null}

                {review.improveNextWeek ? (
                  <p className="text-sm text-zinc-300">
                    <span className="text-zinc-500">{t('reviews.improveNextWeek')}: </span>
                    {review.improveNextWeek}
                  </p>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
