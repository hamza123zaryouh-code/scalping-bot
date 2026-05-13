import { NextResponse } from 'next/server'

const PUBLIC_PATHS = ['/login', '/register']

export function proxy(request) {
  const { pathname } = request.nextUrl
  const isPublicPath = PUBLIC_PATHS.includes(pathname)
  const hasSessionCookie = Boolean(request.cookies.get('sb-access-token')?.value)

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
