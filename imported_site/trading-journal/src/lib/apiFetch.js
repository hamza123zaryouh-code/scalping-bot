/**
 * Wrapper around fetch that handles session expiry (HTTP 401).
 * On 401, clears local state and redirects to /login.
 */
export async function apiFetch(url, options = {}) {
  const response = await fetch(url, options)

  if (response.status === 401) {
    // Clear the session cookie by calling logout, then redirect.
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
    window.location.replace('/login')
    // Return a never-resolving promise so callers don't continue.
    return new Promise(() => {})
  }

  return response
}
