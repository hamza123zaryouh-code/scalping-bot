import { requireAuthenticatedUser } from '@/lib/authServer'
import { getProfile, isMissingTableError, upsertProfile } from '@/lib/tradeRepository'

const PROFILE_MIGRATION_WARNING =
  'Profile table is missing in Supabase. Run supabase/schema.sql to enable persistent profile settings.'

const SUPPORTED_LANGUAGES = ['nl', 'en', 'ar']

function normalizeLanguage(value) {
  if (!value || !SUPPORTED_LANGUAGES.includes(value)) return 'nl'
  return value
}

function normalizeCurrency(value) {
  const currency = String(value || 'EUR').trim().toUpperCase()
  return currency || 'EUR'
}

export async function GET() {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const profile = await getProfile(auth.supabase, auth.user.id, auth.user)

    if (profile.migrationMissing) {
      return Response.json({ profile, warning: PROFILE_MIGRATION_WARNING })
    }

    return Response.json({ profile })
  } catch (error) {
    console.error('[GET /api/profile]', error)
    return Response.json({ error: 'Failed to load profile.' }, { status: 500 })
  }
}

export async function PUT(request) {
  const auth = await requireAuthenticatedUser()
  if (auth.error) return auth.error

  try {
    const payload = await request.json()

    const updates = {
      displayName: 'displayName' in payload ? String(payload.displayName || '').trim() : undefined,
      language: 'language' in payload ? normalizeLanguage(payload.language) : undefined,
      currency: 'currency' in payload ? normalizeCurrency(payload.currency) : undefined,
      preferredCurrency: 'preferredCurrency' in payload ? normalizeCurrency(payload.preferredCurrency) : undefined,
      usdToEurRate: 'usdToEurRate' in payload ? (Number(payload.usdToEurRate) || null) : undefined,
      avatarUrl: 'avatarUrl' in payload ? (payload.avatarUrl ?? null) : undefined,
      accountBalance: 'accountBalance' in payload ? (Number(payload.accountBalance) || null) : undefined,
      ftmoAccountSize: 'ftmoAccountSize' in payload ? (Number(payload.ftmoAccountSize) || null) : undefined,
      dailyLossLimit: 'dailyLossLimit' in payload ? (Number(payload.dailyLossLimit) || null) : undefined,
      maxLossLimit: 'maxLossLimit' in payload ? (Number(payload.maxLossLimit) || null) : undefined,
      maxTradesPerDay: 'maxTradesPerDay' in payload ? (Number(payload.maxTradesPerDay) || null) : undefined,
      maxRiskPerDay: 'maxRiskPerDay' in payload ? (Number(payload.maxRiskPerDay) || null) : undefined,
      dailyProfitTarget: 'dailyProfitTarget' in payload ? (Number(payload.dailyProfitTarget) || null) : undefined,
    }

    let warning = null
    try {
      await upsertProfile(auth.supabase, auth.user.id, updates)
    } catch (profileError) {
      if (isMissingTableError(profileError, 'profiles')) {
        warning = PROFILE_MIGRATION_WARNING
      } else {
        throw profileError
      }
    }

    const profile = await getProfile(auth.supabase, auth.user.id, {
      ...auth.user,
      user_metadata: {
        ...auth.user.user_metadata,
        ...(updates.displayName !== undefined && { display_name: updates.displayName || auth.user.user_metadata?.display_name || null }),
        ...(updates.language !== undefined && { language: updates.language }),
        ...(updates.currency !== undefined && { currency: updates.currency }),
      },
    })

    if (warning || profile.migrationMissing) {
      return Response.json({ profile, warning: warning ?? PROFILE_MIGRATION_WARNING })
    }

    return Response.json({ profile })
  } catch (error) {
    console.error('[PUT /api/profile] code=%s message=%s', error?.code, error?.message, error)
    return Response.json({ error: 'Failed to update profile.' }, { status: 500 })
  }
}
