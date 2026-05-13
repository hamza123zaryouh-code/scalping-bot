import { requireAuthenticatedUser } from '@/lib/authServer'
import { isTradeSchemaCompatibilityError, listTrades } from '@/lib/tradeRepository'
import { tradesToCSV } from '@/lib/tradeUtils'

const TRADES_MIGRATION_WARNING =
  'Trades table is outdated or missing columns in Supabase. Run supabase/schema.sql on the production database.'

export async function GET() {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const trades = await listTrades(auth.supabase, auth.user.id)
    const csv = tradesToCSV(trades)
    const filename = `trades-${new Date().toISOString().slice(0, 10)}.csv`

    return new Response(csv, {
      headers: {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="${filename}"`,
      },
    })
  } catch (error) {
    if (isTradeSchemaCompatibilityError(error)) {
      return Response.json({ error: TRADES_MIGRATION_WARNING }, { status: 409 })
    }

    console.error('[GET /api/export]', error)
    return Response.json({ error: 'Failed to export trades.' }, { status: 500 })
  }
}
