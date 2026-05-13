'use client'

import { useEffect, useRef, useState } from 'react'
import Image from 'next/image'
import { useRouter } from 'next/navigation'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useToast } from '@/components/ToastProvider'
import { useAuth } from '@/components/AuthSessionProvider'
import { useRefreshProfile } from '@/components/ProfileProvider'
import { LANGUAGES, useTranslation } from '@/lib/i18n'
import {
  getStoredAvatarUrl,
  removeStoredAvatarUrl,
  setStoredAvatarUrl,
} from '@/lib/avatarStorage'

const inputClass =
  'w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:border-emerald-600 focus:outline-none'

const MAX_AVATAR_BYTES = 5 * 1024 * 1024

const DEFAULT_FORM = {
  displayName: '',
  email: '',
  language: 'nl',
  currency: 'EUR',
  usdToEurRate: '',
  accountBalance: '',
  ftmoAccountSize: '',
  dailyLossLimit: '',
  maxLossLimit: '',
  maxTradesPerDay: '',
  maxRiskPerDay: '',
  dailyProfitTarget: '',
}

export default function ProfilePage() {
  const router = useRouter()
  const toast = useToast()
  const { t, setLanguage } = useTranslation()
  const { user, signOut } = useAuth()
  const refreshProfile = useRefreshProfile()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [form, setForm] = useState(DEFAULT_FORM)
  const [avatarUrl, setAvatarUrl] = useState(null)
  const fileInputRef = useRef(null)

  useEffect(() => {
    fetch('/api/profile')
      .then((response) => response.json())
      .then((data) => {
        if (!data.profile) return

        const p = data.profile
        setForm({
          displayName: p.displayName || '',
          email: p.email || '',
          language: p.language || 'nl',
          currency: p.currency || 'EUR',
          usdToEurRate: p.usdToEurRate != null ? String(p.usdToEurRate) : '',
          accountBalance: p.accountBalance != null ? String(p.accountBalance) : '',
          ftmoAccountSize: p.ftmoAccountSize != null ? String(p.ftmoAccountSize) : '',
          dailyLossLimit: p.dailyLossLimit != null ? String(p.dailyLossLimit) : '',
          maxLossLimit: p.maxLossLimit != null ? String(p.maxLossLimit) : '',
          maxTradesPerDay: p.maxTradesPerDay != null ? String(p.maxTradesPerDay) : '',
          maxRiskPerDay: p.maxRiskPerDay != null ? String(p.maxRiskPerDay) : '',
          dailyProfitTarget: p.dailyProfitTarget != null ? String(p.dailyProfitTarget) : '',
        })
        setAvatarUrl(p.avatarUrl || getStoredAvatarUrl(user?.id) || null)
        setLanguage(p.language || 'nl')

        if (data.warning) toast(data.warning, 'info')
      })
      .finally(() => setLoading(false))
  }, [setLanguage, toast, user?.id])

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleAvatarUpload(event) {
    const file = event.target.files?.[0]
    if (!file || !user) return

    if (!file.type.startsWith('image/')) {
      toast('Kies een geldig afbeeldingsbestand.', 'error')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    if (file.size > MAX_AVATAR_BYTES) {
      toast('Foto is te groot. Kies een afbeelding kleiner dan 5 MB.', 'error')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    setUploading(true)

    const formData = new FormData()
    formData.set('avatar', file)

    const response = await fetch('/api/profile/avatar', {
      method: 'POST',
      body: formData,
    })

    const data = await response.json().catch(() => ({}))
    setUploading(false)

    if (!response.ok || !data.profile?.avatarUrl) {
      toast(data.error || t('profile.avatarError'), 'error')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    setStoredAvatarUrl(user.id, data.profile.avatarUrl)
    setAvatarUrl(data.profile.avatarUrl)
    if (data.warning) toast(data.warning, 'info')
    toast(t('profile.avatarSaved'))
    if (fileInputRef.current) fileInputRef.current.value = ''
    refreshProfile()
  }

  async function handleAvatarDelete() {
    if (!user || !avatarUrl) return

    setUploading(true)

    const response = await fetch('/api/profile/avatar', { method: 'DELETE' })
    const data = await response.json().catch(() => ({}))

    setUploading(false)

    if (!response.ok) {
      toast(data.error || t('profile.avatarError'), 'error')
      return
    }

    removeStoredAvatarUrl(user.id)
    setAvatarUrl(null)
    toast(t('profile.avatarDeleted'))
    refreshProfile()
  }

  async function handleSave(event) {
    event.preventDefault()
    setSaving(true)

    const response = await fetch('/api/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        displayName: form.displayName,
        language: form.language,
        currency: form.currency,
        preferredCurrency: form.currency,
        usdToEurRate: form.usdToEurRate !== '' ? Number(form.usdToEurRate) : null,
        accountBalance: form.accountBalance !== '' ? Number(form.accountBalance) : null,
        ftmoAccountSize: form.ftmoAccountSize !== '' ? Number(form.ftmoAccountSize) : null,
        dailyLossLimit: form.dailyLossLimit !== '' ? Number(form.dailyLossLimit) : null,
        maxLossLimit: form.maxLossLimit !== '' ? Number(form.maxLossLimit) : null,
        maxTradesPerDay: form.maxTradesPerDay !== '' ? Number(form.maxTradesPerDay) : null,
        maxRiskPerDay: form.maxRiskPerDay !== '' ? Number(form.maxRiskPerDay) : null,
        dailyProfitTarget: form.dailyProfitTarget !== '' ? Number(form.dailyProfitTarget) : null,
      }),
    })

    const data = await response.json()
    setSaving(false)

    if (!response.ok) {
      toast(data.error || t('profile.saveFailed'), 'error')
      return
    }

    setLanguage(form.language)
    if (data.warning) toast(data.warning, 'info')
    toast(t('profile.saved'))
    refreshProfile()
  }

  async function handleLogout() {
    setLoggingOut(true)
    await signOut()
    setLoggingOut(false)
    router.replace('/login')
  }

  const displayName = form.displayName || user?.email?.split('@')[0] || 'Trader'

  if (loading) return <LoadingSpinner center />

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">{t('profile.title')}</h1>
        <p className="mt-1 text-sm text-zinc-500">{t('profile.subtitle')}</p>
      </div>

      {/* Avatar */}
      <div className="flex items-center gap-5 rounded-xl border border-zinc-800 bg-zinc-900 p-5">
        {avatarUrl ? (
          <Image
            src={avatarUrl}
            alt={displayName}
            width={80}
            height={80}
            unoptimized
            loading="eager"
            className="h-20 w-20 flex-shrink-0 rounded-full object-cover ring-2 ring-zinc-700"
          />
        ) : (
          <div className="flex h-20 w-20 flex-shrink-0 items-center justify-center rounded-full bg-emerald-700 text-2xl font-bold text-white ring-2 ring-zinc-700">
            {displayName.charAt(0).toUpperCase()}
          </div>
        )}

        <div className="space-y-2">
          <p className="text-sm font-medium text-zinc-300">{t('profile.avatar')}</p>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleAvatarUpload}
          />

          <div className="flex gap-2">
            <button
              type="button"
              disabled={uploading}
              onClick={() => fileInputRef.current?.click()}
              className="rounded-lg bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-700 hover:text-white disabled:opacity-60"
            >
              {uploading ? t('profile.uploading') : t('profile.uploadAvatar')}
            </button>

            {avatarUrl && (
              <button
                type="button"
                disabled={uploading}
                onClick={handleAvatarDelete}
                className="rounded-lg bg-red-900/30 px-3 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-900/60 disabled:opacity-60"
              >
                {t('profile.deleteAvatar')}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* General settings */}
      <form onSubmit={handleSave} className="space-y-5 rounded-xl border border-zinc-800 bg-zinc-900 p-6">
        <label className="block space-y-1.5">
          <span className="text-sm text-zinc-400">{t('profile.name')}</span>
          <input
            type="text"
            value={form.displayName}
            onChange={(event) => updateField('displayName', event.target.value)}
            className={inputClass}
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm text-zinc-400">{t('profile.email')}</span>
          <input type="email" value={form.email} className={`${inputClass} opacity-70`} disabled />
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm text-zinc-400">{t('profile.language')}</span>
          <select
            value={form.language}
            onChange={(event) => {
              const value = event.target.value
              updateField('language', value)
              setLanguage(value)
            }}
            className={inputClass}
          >
            {LANGUAGES.map((language) => (
              <option key={language.code} value={language.code}>
                {language.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm text-zinc-400">{t('profile.currency')}</span>
          <select
            value={form.currency}
            onChange={(event) => updateField('currency', event.target.value)}
            className={inputClass}
          >
            <option value="EUR">EUR (€)</option>
            <option value="USD">USD ($)</option>
          </select>
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm text-zinc-400">{t('profile.usdToEurRate')}</span>
          <input
            type="number"
            step="0.0001"
            min="0"
            value={form.usdToEurRate}
            onChange={(event) => updateField('usdToEurRate', event.target.value)}
            placeholder="0.92"
            className={inputClass}
          />
          <span className="block text-xs text-zinc-500">{t('profile.usdToEurHint')}</span>
        </label>

        {/* FTMO section */}
        <div className="space-y-4 border-t border-zinc-700 pt-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
            {t('profile.ftmoSection')}
          </p>

          <label className="block space-y-1.5">
            <span className="text-sm text-zinc-400">{t('profile.accountBalance')}</span>
            <input
              type="number"
              step="1"
              min="0"
              value={form.accountBalance}
              onChange={(event) => updateField('accountBalance', event.target.value)}
              placeholder="10000"
              className={inputClass}
            />
          </label>

          <label className="block space-y-1.5">
            <span className="text-sm text-zinc-400">{t('profile.ftmoAccountSize')}</span>
            <input
              type="number"
              step="1"
              min="0"
              value={form.ftmoAccountSize}
              onChange={(event) => updateField('ftmoAccountSize', event.target.value)}
              placeholder="10000"
              className={inputClass}
            />
          </label>

          <div className="grid grid-cols-2 gap-4">
            <label className="block space-y-1.5">
              <span className="text-sm text-zinc-400">{t('profile.dailyLossLimit')}</span>
              <input
                type="number"
                step="1"
                min="0"
                value={form.dailyLossLimit}
                onChange={(event) => updateField('dailyLossLimit', event.target.value)}
                placeholder="500"
                className={inputClass}
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm text-zinc-400">{t('profile.maxLossLimit')}</span>
              <input
                type="number"
                step="1"
                min="0"
                value={form.maxLossLimit}
                onChange={(event) => updateField('maxLossLimit', event.target.value)}
                placeholder="1000"
                className={inputClass}
              />
            </label>
          </div>
        </div>

        <div className="space-y-4 border-t border-zinc-700 pt-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500">
            {t('profile.goalsSection')}
          </p>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="block space-y-1.5">
              <span className="text-sm text-zinc-400">{t('profile.maxTradesPerDay')}</span>
              <input
                type="number"
                step="1"
                min="0"
                value={form.maxTradesPerDay}
                onChange={(event) => updateField('maxTradesPerDay', event.target.value)}
                placeholder="3"
                className={inputClass}
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm text-zinc-400">{t('profile.maxRiskPerDay')}</span>
              <input
                type="number"
                step="1"
                min="0"
                value={form.maxRiskPerDay}
                onChange={(event) => updateField('maxRiskPerDay', event.target.value)}
                placeholder="200"
                className={inputClass}
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm text-zinc-400">{t('profile.dailyProfitTarget')}</span>
              <input
                type="number"
                step="1"
                min="0"
                value={form.dailyProfitTarget}
                onChange={(event) => updateField('dailyProfitTarget', event.target.value)}
                placeholder="300"
                className={inputClass}
              />
            </label>
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-lg bg-emerald-600 py-3 text-sm font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-60"
        >
          {saving ? t('profile.saving') : t('profile.save')}
        </button>

        <button
          type="button"
          disabled={loggingOut}
          onClick={handleLogout}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-3 text-sm font-semibold text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-white disabled:opacity-60"
        >
          {loggingOut ? t('profile.loggingOut') : t('nav.logout')}
        </button>
      </form>
    </div>
  )
}
