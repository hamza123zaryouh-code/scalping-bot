'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import TradeForm from '@/components/TradeForm'
import { useToast } from '@/components/ToastProvider'
import { apiFetch } from '@/lib/apiFetch'
import { useTranslation } from '@/lib/i18n'
import { useProfile } from '@/components/ProfileProvider'

export default function NewTradePage() {
  const router = useRouter()
  const toast = useToast()
  const { t } = useTranslation()
  const profile = useProfile()
  const currency = profile?.currency ?? 'EUR'

  async function handleSubmit(formData) {
    const response = await apiFetch('/api/trades', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData),
    })

    const data = await response.json()

    if (!response.ok) {
      toast(data.error || t('tradeForm.saveError'), 'error')
      return
    }

    toast(t('tradeForm.saved'))
    router.push(`/trades/${data.trade.id}`)
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <Link href="/trades" className="text-sm text-zinc-500 hover:text-white">
        {t('tradeForm.backToTrades')}
      </Link>

      <div>
        <h1 className="text-2xl font-bold text-white">{t('tradeForm.newTitle')}</h1>
        <p className="mt-1 text-sm text-zinc-500">{t('tradeForm.newSubtitle')}</p>
      </div>

      <TradeForm
        onSubmit={handleSubmit}
        submitLabel={t('tradeForm.saveButton')}
        currency={currency}
        profile={profile}
      />
    </div>
  )
}
