'use client'

import { usePathname } from 'next/navigation'

export default function AppMain({ children }) {
  const pathname = usePathname()
  const isAuthPage = pathname === '/login' || pathname === '/register'

  return (
    <main className={['mx-auto px-4 sm:px-6 py-6 max-w-7xl', isAuthPage ? '' : 'md:pl-[18.5rem]'].join(' ')}>
      {children}
    </main>
  )
}
