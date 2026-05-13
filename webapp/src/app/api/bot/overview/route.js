import { requireAuthenticatedUser } from '@/lib/authServer'
import { buildOverviewPayload } from '@/lib/botServer'

export async function GET() {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const payload = await buildOverviewPayload(auth.accessToken)
    return Response.json(payload)
  } catch (error) {
    console.error('[GET /api/bot/overview]', error)
    return Response.json({ error: 'Failed to load bot overview.' }, { status: 500 })
  }
}
