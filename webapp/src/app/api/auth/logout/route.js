import { cookies } from 'next/headers'
import { ACCESS_COOKIE, REFRESH_COOKIE } from '@/lib/authServer'

export async function POST() {
  const cookieStore = await cookies()
  cookieStore.delete(ACCESS_COOKIE)
  cookieStore.delete(REFRESH_COOKIE)
  return Response.json({ success: true })
}
