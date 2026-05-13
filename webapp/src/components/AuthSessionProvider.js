'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { readJsonResponse } from '@/lib/http'

const AuthContext = createContext(null)

function mapUser(sessionPayload) {
  if (!sessionPayload?.authenticated || !sessionPayload?.user) return null
  return {
    id: sessionPayload.user.id ?? sessionPayload.user.username,
    email: sessionPayload.user.username,
    role: sessionPayload.user.role ?? 'admin',
    user_metadata: {
      display_name: sessionPayload.user.username,
    },
  }
}

export default function AuthSessionProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadSession = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/auth/session', { cache: 'no-store' })
      const data = await readJsonResponse(response)
      if (!response.ok || !data.authenticated) {
        setSession(null)
        return
      }
      setSession({
        access_token: 'cookie-session',
        user: mapUser(data),
      })
    } catch (error) {
      console.error('[AuthSessionProvider] Failed to load session.', error)
      setSession(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSession()
  }, [loadSession])

  const signIn = useCallback(async ({ username, password }) => {
    setLoading(true)
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await readJsonResponse(response)
      if (!response.ok) {
        return { data: null, error: new Error(data.error || 'Login failed') }
      }
      setSession({
        access_token: data.accessToken ?? 'cookie-session',
        user: mapUser({ authenticated: true, user: data.user }),
      })
      return { data, error: null }
    } catch (error) {
      return { data: null, error }
    } finally {
      setLoading(false)
    }
  }, [])

  const signUp = useCallback(async () => {
    return { data: null, error: new Error('Registration is disabled for this workspace.') }
  }, [])

  const signOut = useCallback(async () => {
    setLoading(true)
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
      setSession(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const value = useMemo(
    () => ({
      loading,
      session,
      user: session?.user ?? null,
      isAuthenticated: Boolean(session?.user),
      signIn,
      signUp,
      signOut,
    }),
    [loading, session, signIn, signOut, signUp]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthSessionProvider')
  }
  return context
}
