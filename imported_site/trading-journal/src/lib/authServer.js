import { cookies } from 'next/headers'
import { createSupabaseServerClient } from '@/lib/supabase'

const ACCESS_COOKIE = 'sb-access-token'
const REFRESH_COOKIE = 'sb-refresh-token'

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
    return { user: null, accessToken: null, supabase: null }
  }

  const supabase = createSupabaseServerClient(accessToken)
  const { data, error } = await supabase.auth.getUser(accessToken)

  if (error || !data?.user) {
    return { user: null, accessToken: null, supabase: null }
  }

  return { user: data.user, accessToken, supabase }
}

export async function requireAuthenticatedUser() {
  try {
    const auth = await getAuthenticatedUser()
    if (!auth.user) {
      return {
        error: Response.json({ error: 'Unauthorized' }, { status: 401 }),
        user: null,
        supabase: null,
      }
    }

    return {
      error: null,
      user: auth.user,
      supabase: auth.supabase,
    }
  } catch (error) {
    console.error('[Auth] Failed to initialize authenticated user.', error)
    return {
      error: Response.json(
        {
          error: error?.message || 'Failed to initialize Supabase authentication.',
        },
        { status: 500 }
      ),
      user: null,
      supabase: null,
    }
  }
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
