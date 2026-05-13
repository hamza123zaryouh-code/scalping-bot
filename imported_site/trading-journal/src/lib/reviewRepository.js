import { toNullableString } from '@/lib/supabase'

function rowToReview(row) {
  if (!row) return null
  return {
    id: row.id,
    userId: row.user_id,
    weekStart: row.week_start,
    wentWell: row.went_well,
    wentWrong: row.went_wrong,
    improveNextWeek: row.improve_next_week,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

export async function listReviews(supabase, userId) {
  const { data, error } = await supabase
    .from('reviews')
    .select('*')
    .eq('user_id', userId)
    .order('week_start', { ascending: false })

  if (error) throw error
  return (data ?? []).map(rowToReview)
}

export async function upsertReview(supabase, userId, payload) {
  if (!payload.weekStart) throw new Error('weekStart is required.')

  const row = {
    user_id: userId,
    week_start: payload.weekStart,
    went_well: toNullableString(payload.wentWell),
    went_wrong: toNullableString(payload.wentWrong),
    improve_next_week: toNullableString(payload.improveNextWeek),
  }

  const { data, error } = await supabase
    .from('reviews')
    .upsert(row, { onConflict: 'user_id,week_start' })
    .select('*')
    .single()

  if (error) throw error
  return rowToReview(data)
}

export async function deleteReview(supabase, userId, reviewId) {
  const { error } = await supabase
    .from('reviews')
    .delete()
    .eq('id', reviewId)
    .eq('user_id', userId)

  if (error) throw error
}
