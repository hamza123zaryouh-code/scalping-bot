import { requireAuthenticatedUser, requirePersistence } from '@/lib/authServer'
import {
  createTrade,
  getProfile,
  isTradeSchemaCompatibilityError,
  listTrades,
  validateTradePayload,
} from '@/lib/tradeRepository'

const TRADES_MIGRATION_WARNING =
  'Trades table is outdated or missing columns in Supabase. Run supabase/schema.sql on the production database.'

export async function GET(request) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error
  const persistenceError = requirePersistence(auth)
  if (persistenceError) return persistenceError

  try {
    const { searchParams } = new URL(request.url)
    const filters = {
      search: searchParams.get('search') ?? '',
      type: searchParams.get('type') ?? '',
      status: searchParams.get('status') ?? '',
      result: searchParams.get('result') ?? '',
      satisfactionEmoji: searchParams.get('satisfactionEmoji') ?? '',
      setupTag: searchParams.get('setupTag') ?? '',
      marker: searchParams.get('marker') ?? '',
      date: searchParams.get('date') ?? '',
      dateFrom: searchParams.get('dateFrom') ?? '',
      dateTo: searchParams.get('dateTo') ?? '',
      sortBy: searchParams.get('sortBy') ?? 'date-desc',
    }

    const trades = await listTrades(auth.supabase, auth.user.id, filters)
    return Response.json({ trades })
  } catch (error) {
    if (isTradeSchemaCompatibilityError(error)) {
      return Response.json(
        {
          error: TRADES_MIGRATION_WARNING,
          trades: [],
        },
        { status: 409 }
      )
    }

    console.error('[GET /api/trades]', error)
    return Response.json({ error: 'Failed to fetch trades.' }, { status: 500 })
  }
}

export async function POST(request) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error
  const persistenceError = requirePersistence(auth)
  if (persistenceError) return persistenceError

  try {
    const payload = await request.json()
    const validationError = validateTradePayload(payload)

    if (validationError) {
      return Response.json({ error: validationError }, { status: 400 })
    }

    const profile = await getProfile(auth.supabase, auth.user.id, auth.user)
    const trade = await createTrade(auth.supabase, auth.user.id, payload, {
      usdToEurRate: profile?.usdToEurRate,
    })
    return Response.json({ trade }, { status: 201 })
  } catch (error) {
    if (isTradeSchemaCompatibilityError(error)) {
      return Response.json({ error: TRADES_MIGRATION_WARNING }, { status: 409 })
    }

    console.error('[POST /api/trades]', error)
    return Response.json({ error: 'Failed to save trade.' }, { status: 500 })
  }
}
