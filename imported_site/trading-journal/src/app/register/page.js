'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useAuth } from '@/components/AuthSessionProvider'
import { LANGUAGES, useTranslation } from '@/lib/i18n'

export default function RegisterPage() {
  const router = useRouter()
  const { signUp, isAuthenticated, loading } = useAuth()
  const { t, language, setLanguage } = useTranslation()

  const [form, setForm] = useState({
    displayName: '',
    email: '',
    password: '',
    confirmPassword: '',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!loading && isAuthenticated) {
      router.replace('/')
    }
  }, [isAuthenticated, loading, router])

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setMessage('')

    if (form.password !== form.confirmPassword) {
      setError(t('auth.passwordMismatch'))
      return
    }

    if (form.password.length < 6) {
      setError(t('auth.passwordTooShort'))
      return
    }

    setSubmitting(true)

    const { data, error: signUpError } = await signUp({
      displayName: form.displayName.trim(),
      email: form.email.trim().toLowerCase(),
      password: form.password,
    })

    setSubmitting(false)

    if (signUpError) {
      setError(signUpError.message || t('auth.registrationFailed'))
      return
    }

    if (!data.session) {
      setMessage(t('auth.emailConfirmation'))
      return
    }

    router.replace('/')
    router.refresh()
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="mb-4 flex justify-end gap-2">
          {LANGUAGES.map((lang) => (
            <button
              key={lang.code}
              onClick={() => setLanguage(lang.code)}
              className={[
                'rounded-lg px-2.5 py-1 text-xs font-semibold transition-colors',
                language === lang.code
                  ? 'bg-emerald-600 text-white'
                  : 'bg-zinc-800 text-zinc-400 hover:text-white',
              ].join(' ')}
            >
              {lang.label}
            </button>
          ))}
        </div>

        <div className="mb-6 flex flex-col items-center gap-2">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-600">
            <svg className="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
            </svg>
          </div>
          <span className="text-sm font-bold text-white">{t('nav.appTitle')}</span>
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-8">
          <h1 className="text-2xl font-bold text-white">{t('auth.registerTitle')}</h1>
          <p className="mt-1 text-sm text-zinc-500">{t('auth.registerSubtitle')}</p>

          <form onSubmit={handleSubmit} className="mt-6 space-y-4">
            {error ? (
              <div className="rounded-lg border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-200">
                {error}
              </div>
            ) : null}

            {message ? (
              <div className="rounded-lg border border-emerald-900 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-200">
                {message}
              </div>
            ) : null}

            <label className="block space-y-1">
              <span className="text-sm text-zinc-400">{t('auth.displayName')}</span>
              <input
                type="text"
                required
                value={form.displayName}
                onChange={(event) => setForm((prev) => ({ ...prev, displayName: event.target.value }))}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-emerald-600"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm text-zinc-400">{t('auth.email')}</span>
              <input
                type="email"
                required
                value={form.email}
                onChange={(event) => setForm((prev) => ({ ...prev, email: event.target.value }))}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-emerald-600"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm text-zinc-400">{t('auth.password')}</span>
              <input
                type="password"
                required
                value={form.password}
                onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-emerald-600"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-sm text-zinc-400">{t('auth.confirmPassword')}</span>
              <input
                type="password"
                required
                value={form.confirmPassword}
                onChange={(event) => setForm((prev) => ({ ...prev, confirmPassword: event.target.value }))}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:outline-none focus:border-emerald-600"
              />
            </label>

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-xl bg-emerald-600 px-4 py-2.5 font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-60"
            >
              {submitting ? t('auth.creating') : t('auth.createAccount')}
            </button>
          </form>

          <p className="mt-5 text-sm text-zinc-500">
            {t('auth.haveAccount')}{' '}
            <Link href="/login" className="text-emerald-400 hover:underline">
              {t('auth.signInLink')}
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
