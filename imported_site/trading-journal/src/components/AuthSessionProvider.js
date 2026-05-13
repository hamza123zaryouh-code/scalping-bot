'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getSupabaseClient } from '@/lib/supabaseClient'

const AuthContext = createContext(null)

async function syncSessionCookies(session) {
  const response = await fetch('/api/auth/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      accessToken: session?.access_token ?? null,
      refreshToken: session?.refresh_token ?? null,
    }),
  })

  if (!response.ok) {
    throw new Error('Failed to sync auth session.')
  }
}

export default function AuthSessionProvider({ children }) {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  const applySession = useCallback(async (nextSession) => {
    await syncSessionCookies(nextSession)
    setSession(nextSession ?? null)
  }, [])

  useEffect(() => {
    let active = true

    async function loadInitialSession() {
      try {
        const supabaseClient = getSupabaseClient()
        const { data, error } = await supabaseClient.auth.getSession()
        if (error) throw error
        if (!active) return
        await applySession(data.session ?? null)
      } catch (error) {
        console.error('[AuthSessionProvider] Failed to load session.', error)
        if (active) {
          setSession(null)
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    void loadInitialSession()

    let subscription = null

    try {
      const supabaseClient = getSupabaseClient()
      const listener = supabaseClient.auth.onAuthStateChange(async (_event, nextSession) => {
        if (!active) return

        setLoading(true)

        try {
          await applySession(nextSession ?? null)
        } catch (error) {
          console.error('[AuthSessionProvider] Failed to sync auth state change.', error)
          if (active) {
            setSession(null)
          }
        } finally {
          if (active) {
            setLoading(false)
          }
        }
      })

      subscription = listener.data.subscription
    } catch (error) {
      console.error('[AuthSessionProvider] Failed to subscribe to auth changes.', error)
    }

    return () => {
      active = false
      subscription?.unsubscribe()
    }
  }, [applySession])

  const signIn = useCallback(async ({ email, password }) => {
    setLoading(true)

    try {
      const supabaseClient = getSupabaseClient()
      const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password })

      if (error) {
        return { data, error }
      }

      await applySession(data.session ?? null)
      return { data, error: null }
    } catch (error) {
      return { data: { session: null, user: null }, error }
    } finally {
      setLoading(false)
    }
  }, [applySession])

  const signUp = useCallback(async ({ displayName, email, password }) => {
    setLoading(true)

    try {
      const supabaseClient = getSupabaseClient()
      const { data, error } = await supabaseClient.auth.signUp({
        email,
        password,
        options: {
          data: {
            display_name: displayName,
            language: 'nl',
            currency: 'EUR',
            preferred_currency: 'EUR',
          },
        },
      })

      if (error) {
        return { data, error }
      }

      if (data.session) {
        await applySession(data.session)
      }

      return { data, error: null }
    } catch (error) {
      return { data: { session: null, user: null }, error }
    } finally {
      setLoading(false)
    }
  }, [applySession])

  const signOut = useCallback(async () => {
    setLoading(true)

    try {
      const supabaseClient = getSupabaseClient()
      await supabaseClient.auth.signOut()
      await applySession(null)
    } finally {
      setLoading(false)
    }
  }, [applySession])

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
