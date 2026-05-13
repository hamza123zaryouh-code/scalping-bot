import { requireAuthenticatedUser } from '@/lib/authServer'
import { BOT_API_BASE, DEV_START_COMMAND } from '@/lib/botServer'

export async function POST(request) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const { equity, dayStartEquity, estimatedTradeRisk } = await request.json()
    const params = new URLSearchParams({
      equity: String(equity),
      day_start_equity: String(dayStartEquity),
      estimated_trade_risk: String(estimatedTradeRisk),
    })

    let response
    try {
      response = await fetch(`${BOT_API_BASE}/risk/ftmo?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${auth.accessToken}`,
        },
        cache: 'no-store',
      })
    } catch {
      return Response.json(
        {
          error: `Bot backend is unavailable at ${BOT_API_BASE}. Start it with: ${DEV_START_COMMAND}`,
        },
        { status: 503 }
      )
    }

    const data = await response.json().catch(() => null)
    if (!response.ok) {
      return Response.json({ error: data?.detail || 'Failed to run risk simulation.' }, { status: response.status })
    }

    return Response.json(data)
  } catch (error) {
    console.error('[POST /api/bot/simulate]', error)
    return Response.json({ error: 'Failed to run risk simulation.' }, { status: 500 })
  }
}
