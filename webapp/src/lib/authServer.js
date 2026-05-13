import { cookies } from 'next/headers'
import { jwtVerify } from 'jose'
import {
  buildAppUser,
  createSupabaseServiceClient,
  ensureSupabaseAppUser,
  getJwtVerificationSecretValue,
  resolvePersistenceMode,
  STORAGE_MODE_UNCONFIGURED,
} from '@/lib/supabase'

const ACCESS_COOKIE = 'bot-access-token'
const REFRESH_COOKIE = 'bot-refresh-token'

function getJwtVerificationSecret() {
  return new TextEncoder().encode(getJwtVerificationSecretValue())
}

export async function verifyAccessToken(token) {
  const { payload } = await jwtVerify(token, getJwtVerificationSecret(), {
    algorithms: ['HS256'],
  })
  return payload
}

export async function getAccessToken() {
  const cookieStore = await cookies()
  return cookieStore.get(ACCESS_COOKIE)?.value ?? null
}

export async function getRefreshToken() {
  const cookieStore = await cookies()
  return cookieStore.get(REFRESH_COOKIE)?.value ?? null
}

export async function getAuthenticatedUser() {
  const accessToken = await getAccessToken()
  if (!accessToken) {
    return { user: null, accessToken: null, payload: null }
  }

  try {
    const payload = await verifyAccessToken(accessToken)
    const user = buildAppUser(payload)
    return { accessToken, payload, user }
  } catch (error) {
    console.error('[Auth] Access token verification failed.', error)
    return { user: null, accessToken: null, payload: null }
  }
}

export async function requireAuthenticatedUser() {
  try {
    const auth = await getAuthenticatedUser()
    if (!auth.user) {
      return {
        error: Response.json({ error: 'Unauthorized' }, { status: 401 }),
        user: null,
        accessToken: null,
        supabase: null,
        storageMode: STORAGE_MODE_UNCONFIGURED,
        storageError: null,
      }
    }

    const persistence = resolvePersistenceMode()
    let supabase = null

    if (persistence.mode === 'supabase') {
      supabase = createSupabaseServiceClient()
      await ensureSupabaseAppUser(supabase, auth.user)
    }

    return {
      error: null,
      user: auth.user,
      accessToken: auth.accessToken,
      supabase,
      storageMode: persistence.mode,
      storageError: persistence.error,
    }
  } catch (error) {
    console.error('[Auth] Failed to initialize authenticated user.', error)
    return {
      error: Response.json({ error: 'Failed to initialize authentication.' }, { status: 500 }),
      user: null,
      accessToken: null,
      supabase: null,
      storageMode: STORAGE_MODE_UNCONFIGURED,
      storageError: null,
    }
  }
}

export function requirePersistence(auth) {
  if (auth.storageMode !== STORAGE_MODE_UNCONFIGURED) {
    return null
  }

  return Response.json(
    {
      error: auth.storageError || 'Persistent storage is not configured.',
    },
    { status: 503 }
  )
}

export function authCookieOptions(maxAgeSeconds = 60 * 60 * 24 * 7) {
  return {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: maxAgeSeconds,
  }
}

export { ACCESS_COOKIE, REFRESH_COOKIE }
