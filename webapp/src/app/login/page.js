'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useAuth } from '@/components/AuthSessionProvider'

export default function LoginPage() {
  const router = useRouter()
  const { signIn, isAuthenticated, loading } = useAuth()
  const [form, setForm] = useState({ username: '', password: '' })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!loading && isAuthenticated) {
      router.replace('/')
    }
  }, [isAuthenticated, loading, router])

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitting(true)
    setError('')

    const { error: signInError } = await signIn({
      username: form.username.trim(),
      password: form.password,
    })

    setSubmitting(false)

    if (signInError) {
      setError(signInError.message || 'Login failed')
      return
    }

    router.replace('/')
    router.refresh()
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-900 p-8">
        <div className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400">XAUUSD Expert Desk</p>
          <h1 className="mt-2 text-2xl font-bold text-white">Backend Login</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Sign in with the FastAPI admin account to use the bot dashboard.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error ? (
            <div className="rounded-lg border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-200">
              {error}
            </div>
          ) : null}

          <label className="block space-y-1">
            <span className="text-sm text-zinc-400">Username</span>
            <input
              type="text"
              required
              value={form.username}
              onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:border-emerald-600 focus:outline-none"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-sm text-zinc-400">Password</span>
            <input
              type="password"
              required
              value={form.password}
              onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-2.5 text-sm text-white focus:border-emerald-600 focus:outline-none"
            />
          </label>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-emerald-600 px-4 py-2.5 font-semibold text-white transition-colors hover:bg-emerald-500 disabled:opacity-60"
          >
            {submitting ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <div className="mt-5 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-3 text-xs text-zinc-500">
          Sign in with the backend admin account configured through <span className="text-zinc-300">AUTH_ADMIN_USERNAME</span> and <span className="text-zinc-300">AUTH_ADMIN_PASSWORD_HASH</span>.
        </div>

        <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-3 text-xs text-zinc-500">
          If login reports that the backend is unavailable, start the API with{' '}
          <span className="text-zinc-300">python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000</span>.
        </div>

      </div>
    </div>
  )
}
