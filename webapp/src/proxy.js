import { NextResponse } from 'next/server'

const PUBLIC_PATHS = ['/login', '/register']
const ACCESS_COOKIE = 'bot-access-token'

export function proxy(request) {
  const { pathname } = request.nextUrl
  const isPublicPath = PUBLIC_PATHS.includes(pathname)
  const hasSessionCookie = Boolean(request.cookies.get(ACCESS_COOKIE)?.value)

  if (!hasSessionCookie && !isPublicPath) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  if (hasSessionCookie && isPublicPath) {
    return NextResponse.redirect(new URL('/', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
}
