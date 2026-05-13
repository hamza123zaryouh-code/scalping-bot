import { hasSupabaseBrowserConfig } from '@/lib/supabase'

export async function POST() {
  if (!hasSupabaseBrowserConfig()) {
    return Response.json(
      {
        error: 'Registration is disabled in local bot mode. Sign in with the backend admin account instead.',
      },
      { status: 403 }
    )
  }

  return Response.json(
    {
      error: 'Public registration is disabled for this workspace. Use the backend admin login instead.',
    },
    { status: 403 }
  )
}
