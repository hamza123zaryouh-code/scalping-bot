'use client'

import { useMemo, useState } from 'react'
import {
  ENTRY_ZONE_PIPS,
  FULL_SL_PIPS,
  SATISFACTION_EMOJIS,
  SETUP_TAGS,
  TRADE_STATUSES,
  calculateProfitLossInCurrency,
  calculateTradeRiskReward,
  formatCurrency,
  getStatusLabelKey,
} from '@/lib/tradeUtils'
import { useToast } from '@/components/ToastProvider'
import { useTranslation } from '@/lib/i18n'

const DEFAULT_FORM = {
  symbol: 'XAUUSD',
  tradeType: 'Buy',
  date: new Date().toISOString().slice(0, 10),
  status: 'open',
  entryPrice: '',
  currentPrice: '',
  lotSize: '',
  entryZoneFrom: '',
  entryZoneTo: '',
  stopLoss: '',
  tp1: '',
  tp2: '',
  tp3: '',
  tp4: '',
  feeling: '',
  reasonForEntry: '',
  satisfactionEmoji: '',
  satisfactionReason: '',
  setupTag: '',
  isFavorite: false,
  isMistake: false,
}

const REQUIRED_FIELDS = [
  'symbol',
  'tradeType',
  'date',
  'entryPrice',
  'lotSize',
  'entryZoneFrom',
  'entryZoneTo',
  'stopLoss',
  'tp1',
  'tp2',
  'tp3',
  'tp4',
  'status',
]

const NULLABLE_INPUT_FIELDS = [
  'entryPrice',
  'currentPrice',
  'lotSize',
  'entryZoneFrom',
  'entryZoneTo',
  'stopLoss',
  'tp1',
  'tp2',
  'tp3',
  'tp4',
  'feeling',
  'reasonForEntry',
  'satisfactionEmoji',
  'satisfactionReason',
  'setupTag',
]

const inputBaseClass =
  'w-full rounded-lg border bg-zinc-800 px-3 py-2.5 text-sm text-white transition-colors focus:outline-none'

function getInputClass(hasError) {
  return hasError
    ? `${inputBaseClass} border-red-700 focus:border-red-500`
    : `${inputBaseClass} border-zinc-700 focus:border-emerald-600`
}

function parseNumberField(value) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return null
  return parsed
}

function isPositiveNumber(value) {
  return Number.isFinite(value) && value > 0
}

function Section({ title, children }) {
  return (
    <section className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">{title}</h2>
      {children}
    </section>
  )
}

function Field({ label, error, hint, children }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-medium text-zinc-400">{label}</span>
      {children}
      {hint && !error ? <span className="block text-xs text-zinc-500">{hint}</span> : null}
      {error ? <span className="block text-xs text-red-400">{error}</span> : null}
    </label>
  )
}

function buildInitialForm(initialValues) {
  const merged = { ...DEFAULT_FORM, ...initialValues }

  if (merged.reasonForEntry === '' && merged.reason) {
    merged.reasonForEntry = merged.reason
  }

  for (const field of NULLABLE_INPUT_FIELDS) {
    if (merged[field] === null || merged[field] === undefined) {
      merged[field] = ''
    }
  }

  return merged
}

export default function TradeForm({
  initialValues = {},
  onSubmit,
  submitLabel,
  currency = 'EUR',
  profile = null,
}) {
  const toast = useToast()
  const { t } = useTranslation()

  const [form, setForm] = useState(() => buildInitialForm(initialValues))
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const entryPriceValue = parseNumberField(form.entryPrice)
  const currentPriceValue = parseNumberField(form.currentPrice)
  const lotSizeValue = parseNumberField(form.lotSize)

  const hasValidEntryAndLot = isPositiveNumber(entryPriceValue) && isPositiveNumber(lotSizeValue)
  const hasValidCurrentPrice = isPositiveNumber(currentPriceValue)

  const previewResult = useMemo(() => {
    if (!hasValidEntryAndLot || !hasValidCurrentPrice) return null

    return calculateProfitLossInCurrency({
      symbol: form.symbol || 'XAUUSD',
      tradeType: form.tradeType,
      entryPrice: entryPriceValue,
      currentPrice: currentPriceValue,
      lotSize: lotSizeValue,
      currency,
      usdToEurRate: profile?.usdToEurRate,
    })
  }, [
    currency,
    form.symbol,
    form.tradeType,
    entryPriceValue,
    currentPriceValue,
    lotSizeValue,
    hasValidCurrentPrice,
    hasValidEntryAndLot,
    profile?.usdToEurRate,
  ])

  const riskPreview = useMemo(() => {
    return calculateTradeRiskReward(
      {
        symbol: form.symbol || 'XAUUSD',
        tradeType: form.tradeType,
        entryPrice: form.entryPrice,
        stopLoss: form.stopLoss,
        lotSize: form.lotSize,
        tp1: form.tp1,
        tp2: form.tp2,
        tp3: form.tp3,
        tp4: form.tp4,
      },
      { ...profile, currency }
    )
  }, [
    currency,
    form.entryPrice,
    form.lotSize,
    form.stopLoss,
    form.symbol,
    form.tp1,
    form.tp2,
    form.tp3,
    form.tp4,
    form.tradeType,
    profile,
  ])

  function updateField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }))

    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: undefined }))
    }
  }

  function validate() {
    const nextErrors = {}

    for (const field of REQUIRED_FIELDS) {
      if (!String(form[field] ?? '').trim()) {
        nextErrors[field] = t('common.required')
      }
    }

    const entryPrice = parseNumberField(form.entryPrice)
    if (entryPrice === null) {
      nextErrors.entryPrice = t('tradeForm.mustBeNumeric')
    } else if (entryPrice <= 0) {
      nextErrors.entryPrice = t('tradeForm.mustBePositive')
    }

    const lotSize = parseNumberField(form.lotSize)
    if (lotSize === null) {
      nextErrors.lotSize = t('tradeForm.mustBeNumeric')
    } else if (lotSize <= 0) {
      nextErrors.lotSize = t('tradeForm.mustBePositive')
    }

    const currentPriceRaw = String(form.currentPrice).trim()
    const currentPrice = parseNumberField(form.currentPrice)

    if (currentPriceRaw.length > 0 && currentPrice === null) {
      nextErrors.currentPrice = t('tradeForm.mustBeNumeric')
    } else if (currentPriceRaw.length > 0 && currentPrice <= 0) {
      nextErrors.currentPrice = t('tradeForm.mustBePositive')
    }

    if (form.status !== 'open' && !isPositiveNumber(currentPrice)) {
      nextErrors.currentPrice = t('tradeForm.currentPriceRequired')
    }

    const entryZoneFrom = parseNumberField(form.entryZoneFrom)
    const entryZoneTo = parseNumberField(form.entryZoneTo)

    if (entryZoneFrom === null) {
      nextErrors.entryZoneFrom = t('tradeForm.mustBeNumeric')
    } else if (entryZoneFrom <= 0) {
      nextErrors.entryZoneFrom = t('tradeForm.mustBePositive')
    }

    if (entryZoneTo === null) {
      nextErrors.entryZoneTo = t('tradeForm.mustBeNumeric')
    } else if (entryZoneTo <= 0) {
      nextErrors.entryZoneTo = t('tradeForm.mustBePositive')
    }

    if (
      isPositiveNumber(entryZoneFrom) &&
      isPositiveNumber(entryZoneTo) &&
      entryZoneTo < entryZoneFrom
    ) {
      nextErrors.entryZoneTo = t('tradeForm.zoneMustBeGreater')
    }

    const stopLoss = parseNumberField(form.stopLoss)
    const tp1 = parseNumberField(form.tp1)
    const tp2 = parseNumberField(form.tp2)
    const tp3 = parseNumberField(form.tp3)
    const tp4 = parseNumberField(form.tp4)

    if (stopLoss === null) nextErrors.stopLoss = t('tradeForm.mustBeNumeric')
    else if (stopLoss <= 0) nextErrors.stopLoss = t('tradeForm.mustBePositive')

    if (tp1 === null) nextErrors.tp1 = t('tradeForm.mustBeNumeric')
    else if (tp1 <= 0) nextErrors.tp1 = t('tradeForm.mustBePositive')

    if (tp2 === null) nextErrors.tp2 = t('tradeForm.mustBeNumeric')
    else if (tp2 <= 0) nextErrors.tp2 = t('tradeForm.mustBePositive')

    if (tp3 === null) nextErrors.tp3 = t('tradeForm.mustBeNumeric')
    else if (tp3 <= 0) nextErrors.tp3 = t('tradeForm.mustBePositive')

    if (tp4 === null) nextErrors.tp4 = t('tradeForm.mustBeNumeric')
    else if (tp4 <= 0) nextErrors.tp4 = t('tradeForm.mustBePositive')

    const hasDirectionalValues =
      isPositiveNumber(entryPrice) &&
      isPositiveNumber(stopLoss) &&
      isPositiveNumber(tp1) &&
      isPositiveNumber(tp2) &&
      isPositiveNumber(tp3) &&
      isPositiveNumber(tp4)

    if (hasDirectionalValues) {
      if (form.tradeType === 'Buy') {
        if (stopLoss >= entryPrice) nextErrors.stopLoss = t('tradeForm.slBelowEntry')
        if (tp1 <= entryPrice) nextErrors.tp1 = t('tradeForm.tpAboveEntry')
        if (tp2 <= tp1) nextErrors.tp2 = t('tradeForm.tpOrdering')
        if (tp3 <= tp2) nextErrors.tp3 = t('tradeForm.tpOrdering')
        if (tp4 <= tp3) nextErrors.tp4 = t('tradeForm.tpOrdering')
      }

      if (form.tradeType === 'Sell') {
        if (stopLoss <= entryPrice) nextErrors.stopLoss = t('tradeForm.slAboveEntry')
        if (tp1 >= entryPrice) nextErrors.tp1 = t('tradeForm.tpBelowEntry')
        if (tp2 >= tp1) nextErrors.tp2 = t('tradeForm.tpOrdering')
        if (tp3 >= tp2) nextErrors.tp3 = t('tradeForm.tpOrdering')
        if (tp4 >= tp3) nextErrors.tp4 = t('tradeForm.tpOrdering')
      }
    }

    return nextErrors
  }

  async function handleSubmit(event) {
    event.preventDefault()

    const nextErrors = validate()
    setErrors(nextErrors)

    if (Object.keys(nextErrors).length > 0) return

    setSaving(true)

    try {
      await onSubmit({
        symbol: form.symbol,
        tradeType: form.tradeType,
        date: form.date,
        status: form.status,
        entryPrice: Number(form.entryPrice),
        currentPrice: form.currentPrice !== '' ? Number(form.currentPrice) : null,
        lotSize: Number(form.lotSize),
        entryZoneFrom: Number(form.entryZoneFrom),
        entryZoneTo: Number(form.entryZoneTo),
        entryZonePips: ENTRY_ZONE_PIPS,
        totalStopLossPips: FULL_SL_PIPS,
        stopLoss: Number(form.stopLoss),
        tp1: Number(form.tp1),
        tp2: Number(form.tp2),
        tp3: Number(form.tp3),
        tp4: Number(form.tp4),
        feeling: form.feeling,
        reasonForEntry: form.reasonForEntry,
        satisfactionEmoji: form.satisfactionEmoji || null,
        satisfactionReason: form.satisfactionReason,
        setupTag: form.setupTag || null,
        isFavorite: Boolean(form.isFavorite),
        isMistake: Boolean(form.isMistake),
      })
    } catch (error) {
      toast(error?.message || t('tradeForm.saveError'), 'error')
    } finally {
      setSaving(false)
    }
  }

  const shouldShowCurrentPriceWarning = hasValidEntryAndLot && !hasValidCurrentPrice

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <Section title={t('tradeForm.tradeSection')}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('tradeForm.symbol')} error={errors.symbol}>
            <input
              value={form.symbol}
              onChange={(event) => updateField('symbol', event.target.value.toUpperCase())}
              placeholder="XAUUSD"
              className={getInputClass(errors.symbol)}
            />
          </Field>

          <Field label={t('tradeForm.date')} error={errors.date}>
            <input
              type="date"
              value={form.date}
              onChange={(event) => updateField('date', event.target.value)}
              className={getInputClass(errors.date)}
            />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('tradeForm.type')} error={errors.tradeType}>
            <select
              value={form.tradeType}
              onChange={(event) => updateField('tradeType', event.target.value)}
              className={getInputClass(errors.tradeType)}
            >
              <option value="Buy">{t('tradeForm.buy')}</option>
              <option value="Sell">{t('tradeForm.sell')}</option>
            </select>
          </Field>

          <Field label={t('tradeForm.status')} error={errors.status}>
            <select
              value={form.status}
              onChange={(event) => updateField('status', event.target.value)}
              className={getInputClass(errors.status)}
            >
              {TRADE_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {t(getStatusLabelKey(status))}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label={t('tradeForm.entryPrice')} error={errors.entryPrice}>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.entryPrice}
              onChange={(event) => updateField('entryPrice', event.target.value)}
              className={getInputClass(errors.entryPrice)}
            />
          </Field>

          <Field
            label={t('tradeForm.currentPrice')}
            error={errors.currentPrice}
            hint={form.status === 'open' ? t('tradeForm.currentPricePlaceholder') : t('tradeForm.currentPriceRequired')}
          >
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.currentPrice}
              onChange={(event) => updateField('currentPrice', event.target.value)}
              className={getInputClass(errors.currentPrice)}
            />
          </Field>

          <Field label={t('tradeForm.lotSize')} error={errors.lotSize}>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.lotSize}
              onChange={(event) => updateField('lotSize', event.target.value)}
              className={getInputClass(errors.lotSize)}
            />
          </Field>
        </div>
      </Section>

      <Section title={t('tradeForm.strategySection')}>
        <Field label={t('tradeForm.setupTag')}>
          <select
            value={form.setupTag}
            onChange={(event) => updateField('setupTag', event.target.value)}
            className={getInputClass(false)}
          >
            <option value="">{t('tradeForm.noSetupTag')}</option>
            {SETUP_TAGS.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
        </Field>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('tradeForm.entryZoneFrom')} error={errors.entryZoneFrom}>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.entryZoneFrom}
              onChange={(event) => updateField('entryZoneFrom', event.target.value)}
              placeholder={t('tradeForm.entryZonePlaceholder')}
              className={getInputClass(errors.entryZoneFrom)}
            />
          </Field>

          <Field label={t('tradeForm.entryZoneTo')} error={errors.entryZoneTo}>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.entryZoneTo}
              onChange={(event) => updateField('entryZoneTo', event.target.value)}
              placeholder={t('tradeForm.entryZonePlaceholder')}
              className={getInputClass(errors.entryZoneTo)}
            />
          </Field>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('tradeForm.stopLoss')} error={errors.stopLoss}>
            <input
              type="number"
              step="0.01"
              value={form.stopLoss}
              onChange={(event) => updateField('stopLoss', event.target.value)}
              className={getInputClass(errors.stopLoss)}
            />
          </Field>

          <Field label={t('tradeForm.tp1')} error={errors.tp1}>
            <input
              type="number"
              step="0.01"
              value={form.tp1}
              onChange={(event) => updateField('tp1', event.target.value)}
              className={getInputClass(errors.tp1)}
            />
          </Field>

          <Field label={t('tradeForm.tp2')} error={errors.tp2}>
            <input
              type="number"
              step="0.01"
              value={form.tp2}
              onChange={(event) => updateField('tp2', event.target.value)}
              className={getInputClass(errors.tp2)}
            />
          </Field>

          <Field label={t('tradeForm.tp3')} error={errors.tp3}>
            <input
              type="number"
              step="0.01"
              value={form.tp3}
              onChange={(event) => updateField('tp3', event.target.value)}
              className={getInputClass(errors.tp3)}
            />
          </Field>

          <Field label={t('tradeForm.tp4')} error={errors.tp4}>
            <input
              type="number"
              step="0.01"
              value={form.tp4}
              onChange={(event) => updateField('tp4', event.target.value)}
              className={getInputClass(errors.tp4)}
            />
          </Field>
        </div>
      </Section>

      <Section title={t('tradeForm.reflectionSection')}>
        <Field label={t('tradeForm.feeling')}>
          <input
            type="text"
            value={form.feeling}
            maxLength={80}
            onChange={(event) => updateField('feeling', event.target.value)}
            placeholder={t('tradeForm.feelingPlaceholder')}
            className={getInputClass(false)}
          />
        </Field>

        <Field label={t('tradeForm.reasonForEntry')}>
          <textarea
            value={form.reasonForEntry}
            maxLength={300}
            rows={3}
            onChange={(event) => updateField('reasonForEntry', event.target.value)}
            placeholder={t('tradeForm.reasonForEntryPlaceholder')}
            className={`${getInputClass(false)} resize-none`}
          />
        </Field>

        <div className="space-y-2">
          <span className="block text-xs font-medium text-zinc-400">{t('tradeForm.satisfactionEmoji')}</span>
          <div className="flex flex-wrap gap-2">
            {SATISFACTION_EMOJIS.map((emoji) => (
              <button
                key={emoji}
                type="button"
                onClick={() =>
                  updateField('satisfactionEmoji', form.satisfactionEmoji === emoji ? '' : emoji)
                }
                className={[
                  'rounded-lg p-2 text-2xl transition-colors',
                  form.satisfactionEmoji === emoji
                    ? 'bg-emerald-700 ring-2 ring-emerald-400'
                    : 'bg-zinc-800 hover:bg-zinc-700',
                ].join(' ')}
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>

        <Field label={t('tradeForm.satisfactionReason')}>
          <input
            type="text"
            value={form.satisfactionReason}
            maxLength={160}
            onChange={(event) => updateField('satisfactionReason', event.target.value)}
            placeholder={t('tradeForm.satisfactionReasonPlaceholder')}
            className={getInputClass(false)}
          />
        </Field>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => updateField('isFavorite', !form.isFavorite)}
            className={[
              'rounded-lg border px-3 py-2 text-left text-sm transition-colors',
              form.isFavorite
                ? 'border-amber-500 bg-amber-950/40 text-amber-200'
                : 'border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-zinc-600',
            ].join(' ')}
          >
            <span className="font-semibold">{t('tradeForm.favorite')}</span>
            <span className="block text-xs opacity-70">{t('tradeForm.favoriteHint')}</span>
          </button>

          <button
            type="button"
            onClick={() => updateField('isMistake', !form.isMistake)}
            className={[
              'rounded-lg border px-3 py-2 text-left text-sm transition-colors',
              form.isMistake
                ? 'border-red-500 bg-red-950/40 text-red-200'
                : 'border-zinc-700 bg-zinc-800 text-zinc-300 hover:border-zinc-600',
            ].join(' ')}
          >
            <span className="font-semibold">{t('tradeForm.mistake')}</span>
            <span className="block text-xs opacity-70">{t('tradeForm.mistakeHint')}</span>
          </button>
        </div>
      </Section>

      {riskPreview ? (
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
            {t('tradeForm.riskPreview')}
          </h2>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div>
              <p className="text-xs text-zinc-500">{t('tradeForm.riskAmount')}</p>
              <p className="text-sm font-semibold text-red-400">
                {formatCurrency(riskPreview.riskAmount, currency)}
              </p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">{t('tradeForm.riskPercent')}</p>
              <p className="text-sm font-semibold text-white">
                {riskPreview.riskPercent != null ? `${riskPreview.riskPercent.toFixed(2)}%` : '-'}
              </p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">{t('tradeForm.averageRiskReward')}</p>
              <p className="text-sm font-semibold text-white">
                {riskPreview.averageRiskReward != null
                  ? `1:${riskPreview.averageRiskReward.toFixed(2)}`
                  : '-'}
              </p>
            </div>
            {riskPreview.rewards.map((reward) => (
              <div key={reward.key}>
                <p className="text-xs text-zinc-500">{reward.label}</p>
                <p className={reward.amount >= 0 ? 'text-sm font-semibold text-emerald-400' : 'text-sm font-semibold text-red-400'}>
                  {reward.amount != null ? formatCurrency(reward.amount, currency) : '-'}
                </p>
                <p className="text-xs text-zinc-500">
                  {reward.ratio != null ? `1:${reward.ratio.toFixed(2)}` : '-'}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {previewResult !== null ? (
        <div
          className={[
            'rounded-xl border px-5 py-4',
            previewResult > 0
              ? 'border-emerald-800/40 bg-emerald-950/30'
              : previewResult < 0
                ? 'border-red-800/40 bg-red-950/30'
                : 'border-zinc-800 bg-zinc-900',
          ].join(' ')}
        >
          <p className="text-xs uppercase tracking-widest text-zinc-400">{t('tradeForm.previewLabel')}</p>
          <p
            className={[
              'mt-1 text-2xl font-bold',
              previewResult > 0
                ? 'text-emerald-400'
                : previewResult < 0
                  ? 'text-red-400'
                  : 'text-zinc-300',
            ].join(' ')}
          >
            {formatCurrency(previewResult, currency)}
          </p>
          <p className="mt-1 text-xs text-zinc-500">{t('tradeForm.previewNote')}</p>
        </div>
      ) : (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-5 py-4">
          <p className="text-xs uppercase tracking-widest text-zinc-500">{t('tradeForm.previewLabel')}</p>
          <p className="mt-1 text-sm text-zinc-500">
            {shouldShowCurrentPriceWarning
              ? t('tradeForm.currentPriceFallback')
              : t('tradeForm.previewEmpty')}
          </p>
        </div>
      )}

      <button
        type="submit"
        disabled={saving}
        className="w-full rounded-xl bg-emerald-600 py-3 text-sm font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-60"
      >
        {saving ? t('tradeForm.saving') : submitLabel}
      </button>
    </form>
  )
}
