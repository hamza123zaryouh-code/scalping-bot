import { cookies } from 'next/headers'
import { ACCESS_COOKIE, REFRESH_COOKIE, authCookieOptions } from '@/lib/authServer'

export async function POST(request) {
  try {
    const { accessToken, refreshToken } = await request.json()
    const cookieStore = await cookies()

    if (!accessToken) {
      cookieStore.delete(ACCESS_COOKIE)
      cookieStore.delete(REFRESH_COOKIE)
      return Response.json({ success: true })
    }

    cookieStore.set(ACCESS_COOKIE, accessToken, authCookieOptions())

    if (refreshToken) {
      cookieStore.set(REFRESH_COOKIE, refreshToken, authCookieOptions(60 * 60 * 24 * 30))
    }

    return Response.json({ success: true })
  } catch (error) {
    console.error('[POST /api/auth/sync]', error)
    return Response.json({ error: 'Failed to sync auth session.' }, { status: 500 })
  }
}
