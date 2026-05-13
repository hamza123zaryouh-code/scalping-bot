'use client'

import { useCallback, useEffect, useState } from 'react'
import { readJsonResponse } from '@/lib/http'

function unwrapApiSection(section) {
  if (!section || typeof section !== 'object' || !('data' in section)) {
    return section
  }

  const inner = section.data
  if (inner && typeof inner === 'object' && 'data' in inner && 'success' in inner) {
    return {
      ...section,
      data: inner.data,
      meta: {
        success: inner.success,
        message: inner.message,
        timestamp: inner.timestamp,
      },
    }
  }

  return section
}

function normalizeOverviewPayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return payload
  }

  return {
    ...payload,
    risk: unwrapApiSection(payload.risk),
    live: unwrapApiSection(payload.live),
    signal: unwrapApiSection(payload.signal),
    positions: unwrapApiSection(payload.positions),
    analytics: unwrapApiSection(payload.analytics),
  }
}

export function useBotOverview(errorMessage = 'Failed to load bot overview', refreshMs = 15000) {
  const [payload, setPayload] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(
    async (showLoading = false) => {
      if (showLoading) setLoading(true)

      try {
        const response = await fetch('/api/bot/overview', { cache: 'no-store' })
        const data = await readJsonResponse(response)

        if (!response.ok) {
          throw new Error(data.error || errorMessage)
        }

        setPayload(normalizeOverviewPayload(data))
        setError('')
      } catch (loadError) {
        setError(loadError?.message || errorMessage)
      } finally {
        setLoading(false)
      }
    },
    [errorMessage]
  )

  useEffect(() => {
    let active = true

    async function initialLoad() {
      await load(true)
    }

    void initialLoad()

    const interval = window.setInterval(() => {
      if (!active) return
      void load(false)
    }, refreshMs)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [load, refreshMs])

  return {
    payload,
    loading,
    error,
    refresh: () => load(false),
  }
}
