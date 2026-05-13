import { requireAuthenticatedUser } from '@/lib/authServer'

export async function requireAuth() {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return { user: null, supabase: null }
  return { user: auth.user, supabase: auth.supabase }
}

export function unauthorized() {
  return Response.json({ error: 'Unauthorized' }, { status: 401 })
}
