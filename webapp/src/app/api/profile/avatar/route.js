import { requireAuthenticatedUser, requirePersistence } from '@/lib/authServer'
import { getProfile, upsertProfile } from '@/lib/tradeRepository'

const AVATAR_BUCKET = 'avatars'
const MAX_AVATAR_BYTES = 5 * 1024 * 1024
const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif'])

function extensionForFile(file) {
  const type = String(file.type || '').toLowerCase()

  if (type === 'image/jpeg') return 'jpg'
  if (type === 'image/png') return 'png'
  if (type === 'image/webp') return 'webp'
  if (type === 'image/gif') return 'gif'

  const ext = String(file.name || '').split('.').pop()?.toLowerCase()
  return ext || 'jpg'
}

function storagePathFromPublicUrl(url, userId) {
  if (!url) return null

  try {
    const parsed = new URL(url)
    const prefix = `/storage/v1/object/public/${AVATAR_BUCKET}/`
    const path = parsed.pathname.split(prefix).pop()

    if (!path || !path.startsWith(`${userId}/`)) return null
    return path
  } catch {
    return null
  }
}

function buildFallbackProfile(auth, avatarUrl) {
  return {
    userId: auth.user.id,
    email: auth.user.email ?? '',
    displayName: auth.user.user_metadata?.display_name || auth.user.email?.split('@')[0] || '',
    language: auth.user.user_metadata?.language || 'nl',
    currency: auth.user.user_metadata?.currency || 'EUR',
    avatarUrl,
    avatarPersisted: false,
  }
}

export async function POST(request) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error
  const persistenceError = requirePersistence(auth)
  if (persistenceError) return persistenceError

  try {
    const formData = await request.formData()
    const file = formData.get('avatar')

    if (!file || typeof file.arrayBuffer !== 'function') {
      return Response.json({ error: 'Geen foto ontvangen.' }, { status: 400 })
    }

    if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
      return Response.json({ error: 'Kies een JPG, PNG, WebP of GIF afbeelding.' }, { status: 400 })
    }

    if (file.size > MAX_AVATAR_BYTES) {
      return Response.json({ error: 'Foto is te groot. Kies een afbeelding kleiner dan 5 MB.' }, { status: 400 })
    }

    const ext = extensionForFile(file)
    const path = `${auth.user.id}/avatar.${ext}`
    const bytes = await file.arrayBuffer()

    if (!auth.supabase?.storage) {
      const dataUrl = `data:${file.type};base64,${Buffer.from(bytes).toString('base64')}`
      const profile = await upsertProfile(auth.supabase, auth.user.id, { avatarUrl: dataUrl })
      return Response.json({ profile })
    }

    const { error: uploadError } = await auth.supabase.storage
      .from(AVATAR_BUCKET)
      .upload(path, bytes, {
        upsert: true,
        contentType: file.type,
      })

    if (uploadError) {
      return Response.json({ error: uploadError.message || 'Foto uploaden mislukt.' }, { status: 400 })
    }

    const { data: urlData } = auth.supabase.storage.from(AVATAR_BUCKET).getPublicUrl(path)
    const publicUrl = `${urlData.publicUrl}?t=${Date.now()}`

    let profile = null

    try {
      profile = await upsertProfile(auth.supabase, auth.user.id, { avatarUrl: publicUrl })
    } catch (profileError) {
      return Response.json({
        profile: buildFallbackProfile(auth, publicUrl),
        warning:
          profileError?.message ||
          'Foto is geupload, maar kon niet worden opgeslagen in de database. De foto blijft lokaal zichtbaar.',
      })
    }

    if (!profile?.avatarUrl) {
      return Response.json({
        profile: buildFallbackProfile(auth, publicUrl),
        warning: 'Foto is geupload, maar niet opgeslagen in de database. De foto blijft lokaal zichtbaar.',
      })
    }

    return Response.json({ profile })
  } catch (error) {
    console.error('[POST /api/profile/avatar]', error)
    return Response.json({ error: 'Foto uploaden mislukt.' }, { status: 500 })
  }
}

export async function DELETE() {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error
  const persistenceError = requirePersistence(auth)
  if (persistenceError) return persistenceError

  try {
    if (!auth.supabase?.storage) {
      const nextProfile = await upsertProfile(auth.supabase, auth.user.id, { avatarUrl: null })
      return Response.json({ profile: nextProfile })
    }

    const profile = await getProfile(auth.supabase, auth.user.id, auth.user)
    const path = storagePathFromPublicUrl(profile?.avatarUrl, auth.user.id)

    if (path) {
      const { error: removeError } = await auth.supabase.storage.from(AVATAR_BUCKET).remove([path])

      if (removeError) {
        return Response.json({ error: removeError.message || 'Foto verwijderen mislukt.' }, { status: 400 })
      }
    }

    const nextProfile = await upsertProfile(auth.supabase, auth.user.id, { avatarUrl: null })

    return Response.json({ profile: nextProfile })
  } catch (error) {
    console.error('[DELETE /api/profile/avatar]', error)
    return Response.json({ error: 'Foto verwijderen mislukt.' }, { status: 500 })
  }
}
