const AVATAR_STORAGE_PREFIX = 'tj-avatar-url:'

function keyForUser(userId) {
  return `${AVATAR_STORAGE_PREFIX}${userId}`
}

export function getStoredAvatarUrl(userId) {
  if (!userId || typeof window === 'undefined') return null
  return localStorage.getItem(keyForUser(userId))
}

export function setStoredAvatarUrl(userId, avatarUrl) {
  if (!userId || !avatarUrl || typeof window === 'undefined') return
  localStorage.setItem(keyForUser(userId), avatarUrl)
}

export function removeStoredAvatarUrl(userId) {
  if (!userId || typeof window === 'undefined') return
  localStorage.removeItem(keyForUser(userId))
}

export function applyAvatarFallback(profile, userId) {
  if (!profile) return profile
  return {
    ...profile,
    avatarUrl: profile.avatarUrl || getStoredAvatarUrl(userId),
  }
}
