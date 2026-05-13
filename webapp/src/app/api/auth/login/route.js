import { cookies } from 'next/headers'
import {
  ACCESS_COOKIE,
  authCookieOptions,
  verifyAccessToken,
} from '@/lib/authServer'
import { buildAppUser } from '@/lib/supabase'

const BOT_API_BASE = process.env.BOT_API_BASE || 'http://127.0.0.1:8000/api/v1'
const DEV_START_COMMAND = 'python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000'

async function readBackendPayload(response) {
  const contentType = response.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    return response.json().catch(() => ({}))
  }

  const text = await response.text().catch(() => '')
  return text ? { error: text } : {}
}

function buildLoginSuccess(accessToken, user) {
  return {
    ok: true,
    accessToken,
    mode: 'backend',
    user: {
      id: user.id,
      username: user.username,
      role: user.role,
    },
  }
}

export async function POST(request) {
  try {
    const { username, password } = await request.json()
    const normalizedUsername = String(username ?? '').trim()
    const normalizedPassword = String(password ?? '')

    if (!normalizedUsername || !normalizedPassword) {
      return Response.json({ error: 'Username and password are required.' }, { status: 400 })
    }

    const body = new URLSearchParams()
    body.set('username', normalizedUsername)
    body.set('password', normalizedPassword)

    let response
    try {
      response = await fetch(`${BOT_API_BASE}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
        cache: 'no-store',
      })
    } catch (error) {
      console.error('[POST /api/auth/login] Backend auth request failed.', error)
      return Response.json(
        {
          error: `Authentication backend is unavailable at ${BOT_API_BASE}. Start the API with: ${DEV_START_COMMAND}`,
        },
        { status: 503 }
      )
    }

    const data = await readBackendPayload(response)
    if (!response.ok || !data.access_token) {
      return Response.json(
        { error: data.detail || data.error || 'Incorrect username or password' },
        { status: response.status || 401 }
      )
    }

    let payload
    try {
      payload = await verifyAccessToken(data.access_token)
    } catch (error) {
      console.error('[POST /api/auth/login] Backend returned an invalid token.', error)
      return Response.json({ error: 'Authentication backend returned an invalid token.' }, { status: 502 })
    }

    const user = buildAppUser(payload)

    const cookieStore = await cookies()
    cookieStore.set(ACCESS_COOKIE, data.access_token, authCookieOptions())

    return Response.json(buildLoginSuccess(data.access_token, user))
  } catch (error) {
    console.error('[POST /api/auth/login]', error)
    return Response.json({ error: 'Failed to authenticate with backend.' }, { status: 500 })
  }
}
