import { randomUUID } from 'crypto'
import { readJournalStore, updateJournalStore } from '@/lib/journalStore'
import { toNullableString } from '@/lib/supabase'

function hasSupabaseClient(supabase) {
  return Boolean(supabase?.from)
}

function nowIso() {
  return new Date().toISOString()
}

function rowToReview(row) {
  if (!row) return null
  return {
    id: row.id,
    userId: row.user_id ?? row.userId,
    weekStart: row.week_start ?? row.weekStart,
    wentWell: row.went_well ?? row.wentWell,
    wentWrong: row.went_wrong ?? row.wentWrong,
    improveNextWeek: row.improve_next_week ?? row.improveNextWeek,
    createdAt: row.created_at ?? row.createdAt,
    updatedAt: row.updated_at ?? row.updatedAt,
  }
}

export async function listReviews(supabase, userId) {
  if (!hasSupabaseClient(supabase)) {
    const store = await readJournalStore()
    return store.reviews
      .map(rowToReview)
      .filter((review) => review.userId === userId)
      .sort((a, b) => String(b.weekStart || '').localeCompare(String(a.weekStart || '')))
  }

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

  if (!hasSupabaseClient(supabase)) {
    let review = null

    await updateJournalStore((store) => {
      const existing = store.reviews.find(
        (row) => row.userId === userId && row.weekStart === payload.weekStart
      )
      const timestamp = nowIso()

      review = {
        id: existing?.id ?? randomUUID(),
        userId,
        weekStart: payload.weekStart,
        wentWell: toNullableString(payload.wentWell),
        wentWrong: toNullableString(payload.wentWrong),
        improveNextWeek: toNullableString(payload.improveNextWeek),
        createdAt: existing?.createdAt ?? timestamp,
        updatedAt: timestamp,
      }

      store.reviews = store.reviews.filter(
        (row) => !(row.userId === userId && row.weekStart === payload.weekStart)
      )
      store.reviews.push(review)
      return store
    })

    return review
  }

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
  if (!hasSupabaseClient(supabase)) {
    await updateJournalStore((store) => {
      store.reviews = store.reviews.filter(
        (row) => !(row.id === reviewId && row.userId === userId)
      )
      return store
    })
    return
  }

  const { error } = await supabase
    .from('reviews')
    .delete()
    .eq('id', reviewId)
    .eq('user_id', userId)

  if (error) throw error
}
