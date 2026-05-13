import { requireAuthenticatedUser } from '@/lib/authServer'
import { listReviews, upsertReview } from '@/lib/reviewRepository'
import { isMissingTableError } from '@/lib/tradeRepository'

const REVIEWS_MIGRATION_WARNING =
  'Reviews table is missing in Supabase. Run supabase/schema.sql to enable weekly reviews.'

export async function GET() {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const reviews = await listReviews(auth.supabase, auth.user.id)
    return Response.json({ reviews })
  } catch (error) {
    if (isMissingTableError(error, 'reviews')) {
      return Response.json({
        reviews: [],
        warning: REVIEWS_MIGRATION_WARNING,
      })
    }

    console.error('[GET /api/reviews]', error)
    return Response.json({ error: 'Failed to fetch reviews.' }, { status: 500 })
  }
}

export async function POST(request) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const payload = await request.json()

    if (!payload.weekStart) {
      return Response.json({ error: 'weekStart is required.' }, { status: 400 })
    }

    const review = await upsertReview(auth.supabase, auth.user.id, payload)
    return Response.json({ review }, { status: 200 })
  } catch (error) {
    if (isMissingTableError(error, 'reviews')) {
      return Response.json({ error: REVIEWS_MIGRATION_WARNING }, { status: 409 })
    }

    console.error('[POST /api/reviews]', error)
    return Response.json({ error: 'Failed to save review.' }, { status: 500 })
  }
}
