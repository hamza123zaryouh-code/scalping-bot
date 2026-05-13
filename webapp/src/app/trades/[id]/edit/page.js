'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import LoadingSpinner from '@/components/LoadingSpinner'
import TradeForm from '@/components/TradeForm'
import { useToast } from '@/components/ToastProvider'
import { readJsonResponse } from '@/lib/http'
import { useTranslation } from '@/lib/i18n'
import { useProfile } from '@/components/ProfileProvider'

export default function EditTradePage() {
  const { t } = useTranslation()
  const { id } = useParams()
  const router = useRouter()
  const toast = useToast()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'

  const [trade, setTrade] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/trades/${id}`)
      .then(async (response) => ({ ok: response.ok, data: await readJsonResponse(response) }))
      .then(({ ok, data }) => setTrade(ok ? data.trade ?? null : null))
      .finally(() => setLoading(false))
  }, [id])

  async function handleSubmit(payload) {
    const response = await fetch(`/api/trades/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    const data = await readJsonResponse(response)

    if (!response.ok) {
      throw new Error(data.error || t('tradeForm.updateError'))
    }

    toast(t('tradeForm.updated'))
    router.push(`/trades/${id}`)
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

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <Link href={`/trades/${id}`} className="text-sm text-zinc-500 hover:text-white">
        {t('tradeForm.backToTrade')}
      </Link>

      <div>
        <h1 className="text-2xl font-bold text-white">{t('tradeForm.editTitle')}</h1>
        <p className="mt-1 text-sm text-zinc-500">{trade.symbol}</p>
      </div>

      <TradeForm
        initialValues={trade}
        onSubmit={handleSubmit}
        submitLabel={t('tradeForm.updateButton')}
        currency={currency}
        profile={profile}
      />
    </div>
  )
}
