import { getAuthenticatedUser } from '@/lib/authServer'

export async function GET() {
  const auth = await getAuthenticatedUser()
  if (!auth.user) {
    return Response.json({ authenticated: false })
  }

  return Response.json({
    authenticated: true,
    user: {
      id: auth.user.id,
      username: auth.user.username,
      role: auth.user.role ?? 'admin',
    },
  })
}
