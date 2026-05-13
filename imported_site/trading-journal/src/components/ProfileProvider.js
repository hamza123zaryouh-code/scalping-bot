'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from '@/components/AuthSessionProvider'
import { applyAvatarFallback } from '@/lib/avatarStorage'

const ProfileContext = createContext({ profile: null, refreshProfile: () => {} })

export function ProfileProvider({ children }) {
  const { user } = useAuth()
  const [profile, setProfile] = useState(null)

  const loadProfile = useCallback(() => {
    if (!user) return

    let active = true

    fetch('/api/profile')
      .then((r) => r.json())
      .then((d) => {
        if (active) setProfile(applyAvatarFallback(d.profile ?? null, user.id))
      })
      .catch(() => {})

    return () => {
      active = false
    }
  }, [user])

  useEffect(() => {
    if (!user) return

    return loadProfile()
  }, [user, loadProfile])

  const refreshProfile = useCallback(() => {
    loadProfile()
  }, [loadProfile])

  const value = useMemo(
    () => ({
      profile: user && profile?.userId === user.id ? profile : null,
      refreshProfile,
    }),
    [profile, user, refreshProfile]
  )

  return <ProfileContext.Provider value={value}>{children}</ProfileContext.Provider>
}

export function useProfile() {
  return useContext(ProfileContext).profile
}

export function useRefreshProfile() {
  return useContext(ProfileContext).refreshProfile
}
