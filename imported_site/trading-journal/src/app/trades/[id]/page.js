'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import ConfirmModal from '@/components/ConfirmModal'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useToast } from '@/components/ToastProvider'
import { useProfile } from '@/components/ProfileProvider'
import {
  ENTRY_TOLERANCE_PIPS,
  ENTRY_ZONE_PIPS,
  FULL_SL_PIPS,
  REAL_STOP_PIPS,
  calculateTradeR,
  calculateTradeRiskReward,
  formatCurrency,
  convertStoredEurToProfileCurrency,
  formatEntryZone,
  getStatusLabelKey,
  isClosedTradeStatus,
} from '@/lib/tradeUtils'
import { useTranslation } from '@/lib/i18n'
import { formatDate } from '@/lib/utils'

function LevelCard({ label, value, tone = 'default', sub }) {
  const toneClass =
    tone === 'loss'
      ? 'border-red-900 text-red-300'
      : tone === 'profit'
        ? 'border-emerald-900 text-emerald-300'
        : tone === 'zone'
          ? 'border-blue-900 text-blue-300'
          : 'border-zinc-700 text-white'

  return (
    <div className={`rounded-lg border p-3 text-center ${toneClass}`}>
      <p className="text-xs uppercase tracking-widest opacity-70">{label}</p>
      <p className="mt-0.5 text-lg font-bold leading-tight">{value ?? '-'}</p>
      {sub ? <p className="mt-0.5 text-xs opacity-60">{sub}</p> : null}
    </div>
  )
}

export default function TradeDetailPage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const router = useRouter()
  const toast = useToast()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'

  const [trade, setTrade] = useState(null)
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)

  useEffect(() => {
    fetch(`/api/trades/${id}`)
      .then((r) => r.json())
      .then((d) => setTrade(d.trade ?? null))
      .finally(() => setLoading(false))
  }, [id])

  async function handleDelete() {
    setDeleting(true)

    const response = await fetch(`/api/trades/${id}`, { method: 'DELETE' })
    const data = await response.json()

    setDeleting(false)
    setShowDeleteModal(false)

    if (!response.ok) {
      toast(data.error || t('tradeDetail.deleteFailed'), 'error')
      return
    }

    toast(t('tradeDetail.deleteSuccess'))
    router.push('/trades')
  }

  if (loading) return <LoadingSpinner center />

  if (!trade) {
    return (
      <div className="mx-auto max-w-xl text-center">
        <p className="text-zinc-500">{t('tradeDetail.notFound')}</p>
        <Link href="/trades" className="mt-4 inline-block text-sm text-emerald-400 hover:underline">
          {t('tradeDetail.backToTrades')}
        </Link>
      </div>
    )
  }

  const entryZoneLabel = formatEntryZone(trade.entryZoneFrom, trade.entryZoneTo)
  const displayProfitLoss = convertStoredEurToProfileCurrency(trade.profitLoss, profile)
  const hasEntryZone = entryZoneLabel !== null
  const pnlMissing = isClosedTradeStatus(trade.status) && !(Number(trade.currentPrice) > 0)

  const riskInfo = calculateTradeRiskReward(trade, profile)
  const tradeR = calculateTradeR(trade, profile)

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link href="/trades" className="text-xs text-zinc-500 hover:text-white">
            {t('tradeDetail.backToTrades')}
          </Link>
          <h1 className="mt-1 text-2xl font-bold text-white">{trade.symbol}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            <span
              className={`rounded px-2 py-0.5 text-xs font-semibold ${
                trade.tradeType === 'Buy' ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'
              }`}
            >
              {trade.tradeType === 'Buy' ? t('trades.buy') : t('trades.sell')}
            </span>
            <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300">
              {t(getStatusLabelKey(trade.status))}
            </span>
            <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
              {formatDate(trade.date)}
            </span>
            {trade.satisfactionEmoji ? (
              <span className="text-xl leading-none">{trade.satisfactionEmoji}</span>
            ) : null}
            {trade.isFavorite ? (
              <span className="rounded bg-amber-950 px-2 py-0.5 text-xs text-amber-300">
                {t('tradeDetail.favorite')}
              </span>
            ) : null}
            {trade.isMistake ? (
              <span className="rounded bg-red-950 px-2 py-0.5 text-xs text-red-300">
                {t('tradeDetail.mistake')}
              </span>
            ) : null}
          </div>
        </div>

        <div className="text-right">
          <p className={`text-2xl font-bold ${Number(trade.profitLoss) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {formatCurrency(displayProfitLoss, currency)}
          </p>
          {pnlMissing && (
            <p className="mt-0.5 text-xs text-amber-400">{t('tradeDetail.priceNeeded')}</p>
          )}
        </div>
      </div>

      {/* Strategy info */}
      <section className="rounded-xl border border-blue-800/40 bg-blue-950/30 px-5 py-4 space-y-1">
        <p className="text-sm font-semibold text-blue-200">{t('tradeDetail.strategyTitle')}</p>
        <p className="text-xs text-blue-400">{t('tradeDetail.strategyLine1', { value: ENTRY_ZONE_PIPS })}</p>
        <p className="text-xs text-blue-400">{t('tradeDetail.strategyLine2', { value: FULL_SL_PIPS })}</p>
        <p className="text-xs text-blue-400">
          {t('tradeDetail.strategyLine3', { tolerance: ENTRY_TOLERANCE_PIPS, stop: REAL_STOP_PIPS })}
        </p>
      </section>

      {/* Price levels */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 space-y-4">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">{t('tradeDetail.levels')}</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <LevelCard label={t('tradeDetail.entryPrice')} value={trade.entryPrice} />

          {hasEntryZone && (
            <LevelCard
              label={t('tradeDetail.entryZone')}
              value={entryZoneLabel}
              tone="zone"
            />
          )}

          {trade.currentPrice != null && trade.currentPrice > 0 && (
            <LevelCard label={t('tradeDetail.currentPrice')} value={trade.currentPrice} />
          )}

          <LevelCard label={t('tradeDetail.stopLoss')} value={trade.stopLoss} tone="loss" />
          <LevelCard label="TP1" value={trade.tp1} tone="profit" />
          <LevelCard label="TP2" value={trade.tp2} tone="profit" />
          <LevelCard label="TP3" value={trade.tp3} tone="profit" />
          <LevelCard label="TP4" value={trade.tp4} tone="profit" />
        </div>
      </section>

      {/* Details */}
      <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 space-y-4">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">{t('tradeDetail.details')}</h2>

        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-zinc-500">{t('tradeDetail.date')}</p>
            <p className="font-medium text-white">{formatDate(trade.date)}</p>
          </div>
          <div>
            <p className="text-zinc-500">{t('tradeDetail.lotSize')}</p>
            <p className="font-medium text-white">{trade.lotSize}</p>
          </div>
        </div>

        {trade.feeling ? (
          <div className="text-sm">
            <p className="text-zinc-500">{t('tradeDetail.feeling')}</p>
            <p className="text-zinc-300">{trade.feeling}</p>
          </div>
        ) : null}

        {trade.reasonForEntry ? (
          <div className="text-sm">
            <p className="text-zinc-500">{t('tradeDetail.reasonForEntry')}</p>
            <p className="whitespace-pre-wrap text-zinc-300">{trade.reasonForEntry}</p>
          </div>
        ) : null}

        {trade.satisfactionEmoji ? (
          <div className="text-sm">
            <p className="text-zinc-500">{t('tradeDetail.satisfactionEmoji')}</p>
            <p className="flex items-center gap-2 mt-0.5">
              <span className="text-2xl leading-none">{trade.satisfactionEmoji}</span>
              {trade.satisfactionReason ? (
                <span className="text-zinc-300">{trade.satisfactionReason}</span>
              ) : null}
            </p>
          </div>
        ) : null}

        {trade.setupTag ? (
          <div className="text-sm">
            <p className="text-zinc-500">{t('tradeDetail.setupTag')}</p>
            <span className="mt-0.5 inline-block rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-300">
              {trade.setupTag}
            </span>
          </div>
        ) : null}
      </section>

      {/* Risk analysis */}
      {riskInfo && (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 space-y-4">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
            {t('tradeDetail.riskSection')}
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <LevelCard
              label={t('tradeDetail.riskAmount')}
              value={formatCurrency(riskInfo.riskAmount, currency)}
              tone="loss"
            />
            <LevelCard
              label={t('tradeDetail.riskPercent')}
              value={
                riskInfo.riskPercent != null
                  ? `${riskInfo.riskPercent.toFixed(2)}%`
                  : t('tradeDetail.noAccount')
              }
              tone={riskInfo.riskPercent != null ? 'loss' : 'default'}
            />
            {riskInfo.averageRiskReward != null && (
              <LevelCard
                label={t('tradeDetail.averageRiskReward')}
                value={`1:${riskInfo.averageRiskReward.toFixed(2)}`}
                tone="profit"
              />
            )}
            {tradeR != null && (
              <LevelCard
                label={t('tradeDetail.rValue')}
                value={`${tradeR >= 0 ? '+' : ''}${tradeR.toFixed(2)}R`}
                tone={tradeR >= 0 ? 'profit' : 'loss'}
              />
            )}
            {riskInfo.rewards.map((reward) => (
              <LevelCard
                key={reward.key}
                label={reward.label}
                value={reward.amount != null ? formatCurrency(reward.amount, currency) : '-'}
                tone={reward.amount >= 0 ? 'profit' : 'loss'}
                sub={reward.ratio != null ? `1:${reward.ratio.toFixed(2)}` : '-'}
              />
            ))}
          </div>
          {riskInfo.riskPercent == null && (
            <p className="text-xs text-zinc-500">{t('tradeDetail.noAccount')}</p>
          )}
        </section>
      )}

      {/* Actions */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          href={`/trades/${id}/edit`}
          className="rounded-lg bg-zinc-800 py-2.5 text-center text-sm font-semibold text-white transition-colors hover:bg-zinc-700"
        >
          {t('tradeDetail.editTrade')}
        </Link>

        <button
          onClick={() => setShowDeleteModal(true)}
          disabled={deleting}
          className="rounded-lg bg-red-900/40 py-2.5 text-sm font-semibold text-red-300 transition-colors hover:bg-red-900/70 disabled:opacity-60"
        >
          {deleting ? t('tradeDetail.deleting') : t('tradeDetail.deleteTrade')}
        </button>
      </div>

      <ConfirmModal
        isOpen={showDeleteModal}
        title={t('tradeDetail.deleteTitle')}
        message={t('tradeDetail.deleteMessage')}
        cancelLabel={t('common.cancel')}
        confirmLabel={t('common.confirm')}
        onCancel={() => setShowDeleteModal(false)}
        onConfirm={handleDelete}
      />
    </div>
  )
}
