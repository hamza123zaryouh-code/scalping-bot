import { requireAuthenticatedUser, requirePersistence } from '@/lib/authServer'
import { deleteReview } from '@/lib/reviewRepository'
import { isMissingTableError } from '@/lib/tradeRepository'

const REVIEWS_MIGRATION_WARNING =
  'Reviews table is missing in Supabase. Run supabase/schema.sql to enable weekly reviews.'

export async function DELETE(request, { params }) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error
  const persistenceError = requirePersistence(auth)
  if (persistenceError) return persistenceError

  const { id } = await params

  try {
    await deleteReview(auth.supabase, auth.user.id, id)
    return Response.json({ success: true })
  } catch (error) {
    if (isMissingTableError(error, 'reviews')) {
      return Response.json({ error: REVIEWS_MIGRATION_WARNING }, { status: 409 })
    }

    console.error('[DELETE /api/reviews/[id]]', error)
    return Response.json({ error: 'Failed to delete review.' }, { status: 500 })
  }
}
