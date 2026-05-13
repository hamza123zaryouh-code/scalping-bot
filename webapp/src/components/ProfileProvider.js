'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from '@/components/AuthSessionProvider'
import { applyAvatarFallback } from '@/lib/avatarStorage'
import { readJsonResponse } from '@/lib/http'

const ProfileContext = createContext({ profile: null, refreshProfile: async () => {} })

function buildFallbackProfile(user) {
  if (!user) return null

  return {
    userId: user.id,
    email: user.email || 'admin',
    displayName: user.user_metadata?.display_name || user.email || 'Operator',
    language: user.user_metadata?.language || 'nl',
    currency: user.user_metadata?.currency || 'EUR',
    preferredCurrency: user.user_metadata?.currency || 'EUR',
    avatarUrl: null,
    usdToEurRate: null,
    accountBalance: null,
    ftmoAccountSize: null,
    dailyLossLimit: null,
    maxLossLimit: null,
    maxTradesPerDay: null,
    maxRiskPerDay: null,
    dailyProfitTarget: null,
  }
}

export function ProfileProvider({ children }) {
  const { user } = useAuth()
  const [profile, setProfile] = useState(null)

  const refreshProfile = useCallback(async () => {
    if (!user) {
      setProfile(null)
      return
    }

    try {
      const response = await fetch('/api/profile', { cache: 'no-store' })
      const data = await readJsonResponse(response)

      if (!response.ok) {
        setProfile(applyAvatarFallback(buildFallbackProfile(user), user.id))
        return
      }

      setProfile(applyAvatarFallback(data.profile ?? buildFallbackProfile(user), user.id))
    } catch {
      setProfile(applyAvatarFallback(buildFallbackProfile(user), user.id))
    }
  }, [user])

  useEffect(() => {
    void refreshProfile()
  }, [refreshProfile])

  const value = useMemo(
    () => ({
      profile,
      refreshProfile,
    }),
    [profile, refreshProfile]
  )

  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

export function useProfile() {
  return useContext(ProfileContext).profile
}

export function useRefreshProfile() {
  return useContext(ProfileContext).refreshProfile
}
