'use client'

import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import LoadingSpinner from '@/components/LoadingSpinner'
import { useAuth } from '@/components/AuthSessionProvider'

export default function AuthGate({ children }) {
  const pathname = usePathname()
  const router = useRouter()
  const { loading, isAuthenticated } = useAuth()

  const isAuthPage = pathname === '/login' || pathname === '/register'

  useEffect(() => {
    if (!loading && !isAuthenticated && !isAuthPage) {
      router.replace('/login')
    }
  }, [isAuthPage, isAuthenticated, loading, router])

  if (isAuthPage) return children
  if (loading) return <LoadingSpinner center />
  if (!isAuthenticated) return <LoadingSpinner center />

  return children
}
