import { createSupabaseServerClient } from '@/lib/supabase'

export async function POST(request) {
  try {
    const { displayName, email, password } = await request.json()

    if (!displayName || !email || !password) {
      return Response.json({ error: 'Display name, email, and password are required.' }, { status: 400 })
    }

    if (String(password).length < 6) {
      return Response.json({ error: 'Password must be at least 6 characters.' }, { status: 400 })
    }

    const supabase = createSupabaseServerClient()
    const { data, error } = await supabase.auth.signUp({
      email: String(email).toLowerCase().trim(),
      password: String(password),
      options: {
        data: {
          display_name: String(displayName).trim(),
          language: 'nl',
          currency: 'EUR',
        },
      },
    })

    if (error) {
      return Response.json({ error: error.message }, { status: 400 })
    }

    return Response.json({ user: data.user, session: data.session }, { status: 201 })
  } catch (error) {
    console.error('[POST /api/register]', error)
    return Response.json({ error: 'Failed to register account.' }, { status: 500 })
  }
}
