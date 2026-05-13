import { cookies } from 'next/headers'
import { createSupabaseServerClient } from '@/lib/supabase'

export async function requireAuth() {
  const cookieStore = await cookies()
  const accessToken = cookieStore.get('sb-access-token')?.value

  if (!accessToken) return { user: null, supabase: null }

  const supabase = createSupabaseServerClient(accessToken)
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser(accessToken)

  if (error || !user) return { user: null, supabase: null }

  return { user, supabase }
}

export function unauthorized() {
  return Response.json({ error: 'Unauthorized' }, { status: 401 })
}
