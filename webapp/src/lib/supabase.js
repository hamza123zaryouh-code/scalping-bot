import { createHash } from 'crypto'
import { createClient } from '@supabase/supabase-js'

export const STORAGE_MODE_SUPABASE = 'supabase'
export const STORAGE_MODE_LOCAL = 'local'
export const STORAGE_MODE_UNCONFIGURED = 'unconfigured'

function readEnvValue(name) {
  return String(process.env[name] || '').trim()
}

function readEnvFlag(name) {
  return readEnvValue(name).toLowerCase() === 'true'
}

export function isProductionRuntime() {
  return ['production'].includes(readEnvValue('APP_ENV').toLowerCase()) || ['production'].includes(readEnvValue('NODE_ENV').toLowerCase())
}

function assertSecretSeparation({ sharedJwtSecret = '', serviceRoleKey = '', anonKey = '' } = {}) {
  if (sharedJwtSecret && serviceRoleKey && sharedJwtSecret === serviceRoleKey) {
    throw new Error('Shared backend JWT secret must be different from SUPABASE_SERVICE_ROLE_KEY.')
  }

  if (sharedJwtSecret && anonKey && sharedJwtSecret === anonKey) {
    throw new Error('Shared backend JWT secret must be different from NEXT_PUBLIC_SUPABASE_ANON_KEY.')
  }

  if (serviceRoleKey && anonKey && serviceRoleKey === anonKey) {
    throw new Error('SUPABASE_SERVICE_ROLE_KEY must be different from NEXT_PUBLIC_SUPABASE_ANON_KEY.')
  }
}

export function getJwtVerificationSecretValue() {
  const explicitSecret = readEnvValue('BACKEND_JWT_SECRET') || readEnvValue('JWT_SHARED_SECRET')
  const fallbackSecret = readEnvValue('SECRET_KEY') || readEnvValue('JWT_SECRET')
  const sharedJwtSecret = explicitSecret || fallbackSecret

  if (!sharedJwtSecret) {
    throw new Error(
      'Missing backend JWT verification secret. Set BACKEND_JWT_SECRET or JWT_SHARED_SECRET, or share SECRET_KEY with the webapp runtime during local development.'
    )
  }

  if (isProductionRuntime() && !explicitSecret) {
    throw new Error(
      'Webapp production runtime must set BACKEND_JWT_SECRET or JWT_SHARED_SECRET explicitly; do not rely on SECRET_KEY or JWT_SECRET fallback.'
    )
  }

  assertSecretSeparation({
    sharedJwtSecret,
    serviceRoleKey: readEnvValue('SUPABASE_SERVICE_ROLE_KEY'),
    anonKey: readEnvValue('NEXT_PUBLIC_SUPABASE_ANON_KEY'),
  })

  return sharedJwtSecret
}

function formatUuidFromBuffer(buffer) {
  const bytes = Buffer.from(buffer.subarray(0, 16))
  bytes[6] = (bytes[6] & 0x0f) | 0x50
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = bytes.toString('hex')
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32),
  ].join('-')
}

export function hasSupabaseBrowserConfig() {
  return Boolean(readEnvValue('NEXT_PUBLIC_SUPABASE_URL') && readEnvValue('NEXT_PUBLIC_SUPABASE_ANON_KEY'))
}

export function hasSupabaseServerConfig() {
  return Boolean(readEnvValue('NEXT_PUBLIC_SUPABASE_URL') && readEnvValue('SUPABASE_SERVICE_ROLE_KEY'))
}

export function isLocalJournalFallbackEnabled() {
  return readEnvFlag('ALLOW_LOCAL_JOURNAL_FALLBACK')
}

export function resolvePersistenceMode() {
  if (hasSupabaseServerConfig()) {
    assertSecretSeparation({
      sharedJwtSecret: readEnvValue('BACKEND_JWT_SECRET') || readEnvValue('JWT_SHARED_SECRET') || readEnvValue('SECRET_KEY') || readEnvValue('JWT_SECRET'),
      serviceRoleKey: readEnvValue('SUPABASE_SERVICE_ROLE_KEY'),
      anonKey: readEnvValue('NEXT_PUBLIC_SUPABASE_ANON_KEY'),
    })

    return { mode: STORAGE_MODE_SUPABASE, error: null }
  }

  if (isProductionRuntime() && isLocalJournalFallbackEnabled()) {
    return {
      mode: STORAGE_MODE_UNCONFIGURED,
      error: 'ALLOW_LOCAL_JOURNAL_FALLBACK must stay disabled in production. Configure NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, and a shared backend JWT secret instead.',
    }
  }

  if (isLocalJournalFallbackEnabled()) {
    return { mode: STORAGE_MODE_LOCAL, error: null }
  }

  return {
    mode: STORAGE_MODE_UNCONFIGURED,
    error:
      'Persistent storage is not configured. Set NEXT_PUBLIC_SUPABASE_URL plus SUPABASE_SERVICE_ROLE_KEY, or explicitly enable ALLOW_LOCAL_JOURNAL_FALLBACK=true for local-only development.',
  }
}

export function getSupabaseBrowserConfig() {
  const supabaseUrl = readEnvValue('NEXT_PUBLIC_SUPABASE_URL')
  const supabaseAnonKey = readEnvValue('NEXT_PUBLIC_SUPABASE_ANON_KEY')

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('Missing Supabase browser env vars: NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY')
  }

  assertSecretSeparation({
    sharedJwtSecret: readEnvValue('BACKEND_JWT_SECRET') || readEnvValue('JWT_SHARED_SECRET') || readEnvValue('SECRET_KEY') || readEnvValue('JWT_SECRET'),
    serviceRoleKey: readEnvValue('SUPABASE_SERVICE_ROLE_KEY'),
    anonKey: supabaseAnonKey,
  })

  return { supabaseUrl, supabaseAnonKey }
}

export function getSupabaseServerConfig() {
  const supabaseUrl = readEnvValue('NEXT_PUBLIC_SUPABASE_URL')
  const serviceRoleKey = readEnvValue('SUPABASE_SERVICE_ROLE_KEY')

  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error('Missing Supabase server env vars: NEXT_PUBLIC_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY')
  }

  assertSecretSeparation({
    sharedJwtSecret: readEnvValue('BACKEND_JWT_SECRET') || readEnvValue('JWT_SHARED_SECRET') || readEnvValue('SECRET_KEY') || readEnvValue('JWT_SECRET'),
    serviceRoleKey,
    anonKey: readEnvValue('NEXT_PUBLIC_SUPABASE_ANON_KEY'),
  })

  return { supabaseUrl, serviceRoleKey }
}

export function createSupabaseServiceClient() {
  const { supabaseUrl, serviceRoleKey } = getSupabaseServerConfig()

  return createClient(supabaseUrl, serviceRoleKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
      detectSessionInUrl: false,
    },
  })
}

export function createStableAppUserId(subject) {
  const normalized = String(subject || '').trim().toLowerCase()
  if (!normalized) {
    throw new Error('Cannot build an app user id without a token subject.')
  }

  const digest = createHash('sha1').update(`xauusd-app-user:${normalized}`).digest()
  return formatUuidFromBuffer(digest)
}

export function buildAppUser(payload) {
  const username = String(payload?.sub || '').trim()
  if (!username) {
    throw new Error('Authenticated token payload is missing the subject.')
  }

  const displayName = String(payload?.name || username).trim() || username
  return {
    id: createStableAppUserId(username),
    username,
    email: String(payload?.email || `${username}@local.invalid`).trim(),
    role: String(payload?.role || 'admin').trim() || 'admin',
    user_metadata: {
      display_name: displayName,
      language: 'nl',
      currency: 'EUR',
    },
  }
}

export async function ensureSupabaseAppUser(supabase, user) {
  const row = {
    id: user.id,
    username: user.username,
    email: user.email,
    role: user.role,
    metadata: user.user_metadata ?? {},
  }

  const { error } = await supabase.from('app_users').upsert(row, { onConflict: 'id' })
  if (error) {
    throw new Error(`Failed to sync Supabase app user: ${error.message || 'unknown error'}`)
  }
}

export function parseNumber(value, fallback = 0) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export function toNullableNumber(value) {
  if (value === '' || value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function toNullableString(value) {
  if (value === null || value === undefined) return null
  const trimmed = String(value).trim()
  return trimmed ? trimmed : null
}
