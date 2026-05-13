'use client'

import { useMemo, useState } from 'react'
import {
  FULL_SL_PIPS,
  TRADE_STATUSES,
  calculateProfitLossInCurrency,
  formatCurrency,
  getStatusLabelKey,
} from '@/lib/tradeUtils'
import { useToast } from '@/components/ToastProvider'
import { apiFetch } from '@/lib/apiFetch'
import { readJsonResponse } from '@/lib/http'
import { useTranslation } from '@/lib/i18n'

const inputClass =
  'w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:border-emerald-600 focus:outline-none'

function autoLevels(entryPrice, tradeType) {
  const entry = Number(entryPrice)
  if (!entry || entry <= 0) return {}

  const dir = tradeType === 'Buy' ? 1 : -1
  return {
    entryZoneFrom: entry,
    entryZoneTo: entry,
    stopLoss: entry - dir * FULL_SL_PIPS,
    tp1: entry + dir * 30,
    tp2: entry + dir * FULL_SL_PIPS,
    tp3: entry + dir * (FULL_SL_PIPS + 30),
    tp4: entry + dir * (FULL_SL_PIPS * 2),
  }
}

export default function QuickTradeModal({
  isOpen,
  onClose,
  onSuccess,
  currency = 'EUR',
  profile = null,
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const [tradeType, setTradeType] = useState('Buy')
  const [entryPrice, setEntryPrice] = useState('')
  const [currentPrice, setCurrentPrice] = useState('')
  const [lotSize, setLotSize] = useState('')
  const [status, setStatus] = useState('open')
  const [saving, setSaving] = useState(false)

  const previewResult = useMemo(() => {
    const entry = Number(entryPrice)
    const current = Number(currentPrice)
    const lot = Number(lotSize)
    if (!entry || entry <= 0 || !current || current <= 0 || !lot || lot <= 0) return null
    return calculateProfitLossInCurrency({
      tradeType,
      entryPrice: entry,
      currentPrice: current,
      lotSize: lot,
      currency,
      usdToEurRate: profile?.usdToEurRate,
    })
  }, [currency, profile?.usdToEurRate, tradeType, entryPrice, currentPrice, lotSize])

  function reset() {
    setTradeType('Buy')
    setEntryPrice('')
    setCurrentPrice('')
    setLotSize('')
    setStatus('open')
  }

  async function handleSubmit(event) {
    event.preventDefault()

    const entry = Number(entryPrice)
    const lot = Number(lotSize)

    if (!entry || entry <= 0) {
      toast(t('tradeForm.mustBePositive'), 'error')
      return
    }
    if (!lot || lot <= 0) {
      toast(t('tradeForm.mustBePositive'), 'error')
      return
    }

    const levels = autoLevels(entry, tradeType)
    const today = new Date().toISOString().slice(0, 10)

    const payload = {
      symbol: 'XAUUSD',
      tradeType,
      date: today,
      status,
      entryPrice: entry,
      currentPrice: Number(currentPrice) > 0 ? Number(currentPrice) : null,
      lotSize: lot,
      ...levels,
    }

    setSaving(true)

    try {
      const response = await apiFetch('/api/trades', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const data = await readJsonResponse(response)

      if (!response.ok) {
        toast(data.error || t('tradeForm.saveError'), 'error')
        return
      }

      toast(t('tradeForm.saved'))
      reset()
      onSuccess?.()
      onClose()
    } catch {
      toast(t('tradeForm.saveError'), 'error')
    } finally {
      setSaving(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      <div className="relative w-full max-w-sm rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <h2 className="text-sm font-semibold text-white">{t('quickTrade.title')}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-white">
            X
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <div className="flex gap-2">
            {['Buy', 'Sell'].map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setTradeType(type)}
                className={[
                  'flex-1 rounded-lg py-2 text-sm font-semibold transition-colors',
                  tradeType === type
                    ? type === 'Buy'
                      ? 'bg-emerald-600 text-white'
                      : 'bg-red-700 text-white'
                    : 'bg-zinc-800 text-zinc-400 hover:text-white',
                ].join(' ')}
              >
                {type === 'Buy' ? t('tradeForm.buy') : t('tradeForm.sell')}
              </button>
            ))}
          </div>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">{t('quickTrade.entryPrice')}</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={entryPrice}
              onChange={(event) => setEntryPrice(event.target.value)}
              className={inputClass}
              required
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">{t('quickTrade.currentPrice')}</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={currentPrice}
              onChange={(event) => setCurrentPrice(event.target.value)}
              className={inputClass}
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">{t('quickTrade.lotSize')}</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={lotSize}
              onChange={(event) => setLotSize(event.target.value)}
              className={inputClass}
              required
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-zinc-400">{t('tradeForm.status')}</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className={inputClass}
            >
              {TRADE_STATUSES.map((tradeStatus) => (
                <option key={tradeStatus} value={tradeStatus}>
                  {t(getStatusLabelKey(tradeStatus))}
                </option>
              ))}
            </select>
          </label>

          {previewResult !== null && (
            <div
              className={[
                'rounded-lg px-3 py-2',
                previewResult > 0
                  ? 'bg-emerald-950/60'
                  : previewResult < 0
                    ? 'bg-red-950/60'
                    : 'bg-zinc-800',
              ].join(' ')}
            >
              <p className="text-xs text-zinc-400">{t('quickTrade.liveResult')}</p>
              <p
                className={[
                  'text-lg font-bold',
                  previewResult > 0
                    ? 'text-emerald-400'
                    : previewResult < 0
                      ? 'text-red-400'
                      : 'text-zinc-300',
                ].join(' ')}
              >
                {formatCurrency(previewResult, currency)}
              </p>
            </div>
          )}

          <p className="text-xs text-zinc-600">{t('quickTrade.autoLevels')}</p>

          <button
            type="submit"
            disabled={saving}
            className="w-full rounded-lg bg-emerald-600 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-60"
          >
            {saving ? t('quickTrade.saving') : t('quickTrade.save')}
          </button>
        </form>
      </div>
    </div>
  )
}
