'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useState } from 'react'
import { useAuth } from '@/components/AuthSessionProvider'
import { useProfile } from '@/components/ProfileProvider'

function NavIcon({ children }) {
  return (
    <span className="flex h-4 w-4 items-center justify-center text-[10px] font-bold uppercase tracking-wide">
      {children}
    </span>
  )
}

export default function Navbar() {
  const pathname = usePathname()
  const router = useRouter()
  const { user, loading, signOut } = useAuth()
  const profile = useProfile()
  const [mobileOpen, setMobileOpen] = useState(false)

  const isAuthPage = pathname === '/login' || pathname === '/register'
  if (isAuthPage || loading || !user) return null

  const navItems = [
    { href: '/', label: 'Overview', icon: 'OV' },
    { href: '/trades', label: 'Live Desk', icon: 'LV' },
    { href: '/statistics', label: 'Analytics', icon: 'AN' },
    { href: '/backtest', label: 'Backtest', icon: 'BT' },
    { href: '/reviews', label: 'Risk Center', icon: 'RK' },
    { href: '/profile', label: 'System', icon: 'SY' },
  ]

  async function handleLogout() {
    await signOut()
    router.replace('/login')
  }

  const displayName = profile?.displayName || user?.email || 'Operator'

  return (
    <>
      <aside className="fixed left-0 top-0 z-40 hidden h-screen w-64 flex-col border-r border-zinc-800 bg-zinc-950 p-5 md:flex">
        <div className="mb-8">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-600 text-xs font-bold text-white">
            XD
          </div>
          <h1 className="mt-3 text-sm font-bold text-white">XAUUSD Desk</h1>
        </div>

        <nav className="flex-1 space-y-1">
          {navItems.map((item) => {
            const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                className={[
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                  active ? 'bg-emerald-600 text-white' : 'text-zinc-400 hover:bg-zinc-900 hover:text-white',
                ].join(' ')}
              >
                <NavIcon>{item.icon}</NavIcon>
                {item.label}
              </Link>
            )
          })}
        </nav>

        <div className="border-t border-zinc-800 pt-4">
          <div className="mb-3 flex items-center gap-3">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-emerald-700 text-sm font-bold text-white">
              {displayName.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-white">{displayName}</p>
              <p className="truncate text-xs text-zinc-500">{user.email}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="mt-3 w-full rounded-lg bg-zinc-900 px-3 py-2 text-left text-sm text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-white"
          >
            Logout
          </button>
        </div>
      </aside>

      <header className="sticky top-0 z-40 border-b border-zinc-800 bg-zinc-950 md:hidden">
        <div className="flex h-14 items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-600 text-[10px] font-bold text-white">
              XD
            </div>
            <span className="text-sm font-semibold text-white">XAUUSD Desk</span>
          </div>
          <button
            onClick={() => setMobileOpen((prev) => !prev)}
            className="flex h-9 w-9 items-center justify-center rounded-lg bg-zinc-900 text-zinc-300 transition-colors hover:bg-zinc-800 hover:text-white"
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          >
            {mobileOpen ? 'X' : 'Menu'}
          </button>
        </div>

        {mobileOpen ? (
          <div className="space-y-2 border-t border-zinc-800 px-4 py-3">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className="flex items-center gap-2.5 rounded-lg bg-zinc-900 px-3 py-2 text-sm text-zinc-300"
              >
                <NavIcon>{item.icon}</NavIcon>
                {item.label}
              </Link>
            ))}

            <button
              onClick={handleLogout}
              className="w-full rounded-lg bg-red-950/40 px-3 py-2 text-left text-sm text-red-300"
            >
              Logout
            </button>
          </div>
        ) : null}
      </header>
    </>
  )
}
