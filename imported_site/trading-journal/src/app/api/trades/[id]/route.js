import { requireAuthenticatedUser } from '@/lib/authServer'
import {
  deleteTrade,
  getProfile,
  getTradeById,
  updateTrade,
  validateTradePayload,
} from '@/lib/tradeRepository'

export async function GET(_request, { params }) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  const { id } = await params
  const trade = await getTradeById(auth.supabase, auth.user.id, id)

  if (!trade) {
    return Response.json({ error: 'Trade not found.' }, { status: 404 })
  }

  return Response.json({ trade })
}

export async function PUT(request, { params }) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  const { id } = await params
  const payload = await request.json()
  const validationError = validateTradePayload(payload)

  if (validationError) {
    return Response.json({ error: validationError }, { status: 400 })
  }

  const profile = await getProfile(auth.supabase, auth.user.id, auth.user)
  const trade = await updateTrade(auth.supabase, auth.user.id, id, payload, {
    usdToEurRate: profile?.usdToEurRate,
  })

  if (!trade) {
    return Response.json({ error: 'Trade not found.' }, { status: 404 })
  }

  return Response.json({ trade })
}

export async function DELETE(_request, { params }) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  const { id } = await params
  const existingTrade = await getTradeById(auth.supabase, auth.user.id, id)

  if (!existingTrade) {
    return Response.json({ error: 'Trade not found.' }, { status: 404 })
  }

  await deleteTrade(auth.supabase, auth.user.id, id)
  return Response.json({ success: true })
}
