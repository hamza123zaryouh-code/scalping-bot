'use client'

import Link from 'next/link'

export default function RegisterPage() {
  return (
    <div className="flex min-h-[80vh] items-center justify-center px-4">
      <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-900 p-8">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400">XAUUSD Expert Desk</p>
        <h1 className="mt-2 text-2xl font-bold text-white">Registration disabled</h1>
        <p className="mt-2 text-sm text-zinc-500">
          This workspace uses the existing backend admin account instead of public sign-up.
        </p>
        <Link
          href="/login"
          className="mt-6 inline-flex rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500"
        >
          Go to login
        </Link>
      </div>
    </div>
  )
}
