import { afterEach, describe, expect, it } from 'vitest'
import {
  buildAppUser,
  createStableAppUserId,
  getJwtVerificationSecretValue,
  resolvePersistenceMode,
  STORAGE_MODE_UNCONFIGURED,
  STORAGE_MODE_LOCAL,
  STORAGE_MODE_SUPABASE,
} from './supabase'

const ORIGINAL_ENV = { ...process.env }

afterEach(() => {
  process.env = { ...ORIGINAL_ENV }
})

describe('resolvePersistenceMode', () => {
  it('prefers Supabase when server config is present', () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://example.supabase.co'
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'service-role-key'
    process.env.ALLOW_LOCAL_JOURNAL_FALLBACK = 'true'

    const mode = resolvePersistenceMode()

    expect(mode.mode).toBe(STORAGE_MODE_SUPABASE)
    expect(mode.error).toBeNull()
  })

  it('falls back to explicit local mode only when the flag is enabled', () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL
    delete process.env.SUPABASE_SERVICE_ROLE_KEY
    process.env.ALLOW_LOCAL_JOURNAL_FALLBACK = 'true'

    const mode = resolvePersistenceMode()

    expect(mode.mode).toBe(STORAGE_MODE_LOCAL)
    expect(mode.error).toBeNull()
  })

  it('returns an explicit configuration error otherwise', () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL
    delete process.env.SUPABASE_SERVICE_ROLE_KEY
    delete process.env.ALLOW_LOCAL_JOURNAL_FALLBACK

    const mode = resolvePersistenceMode()

    expect(mode.mode).toBe(STORAGE_MODE_UNCONFIGURED)
    expect(mode.error).toMatch(/Persistent storage is not configured/)
  })

  it('rejects local journal fallback in production', () => {
    process.env.APP_ENV = 'production'
    delete process.env.NEXT_PUBLIC_SUPABASE_URL
    delete process.env.SUPABASE_SERVICE_ROLE_KEY
    process.env.ALLOW_LOCAL_JOURNAL_FALLBACK = 'true'

    const mode = resolvePersistenceMode()

    expect(mode.mode).toBe(STORAGE_MODE_UNCONFIGURED)
    expect(mode.error).toMatch(/must stay disabled in production/)
  })
})

describe('buildAppUser', () => {
  it('creates a stable UUID-backed app user from a token payload', () => {
    const payload = { sub: 'desk-admin', role: 'admin' }

    const user = buildAppUser(payload)

    expect(user.username).toBe('desk-admin')
    expect(user.id).toBe(createStableAppUserId('desk-admin'))
    expect(user.email).toBe('desk-admin@local.invalid')
  })
})

describe('getJwtVerificationSecretValue', () => {
  it('prefers an explicit shared JWT secret in production', () => {
    process.env.APP_ENV = 'production'
    process.env.BACKEND_JWT_SECRET = 'shared-backend-jwt-secret'
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'service-role-secret'

    expect(getJwtVerificationSecretValue()).toBe('shared-backend-jwt-secret')
  })

  it('rejects SECRET_KEY fallback in production when no explicit shared JWT secret is set', () => {
    process.env.APP_ENV = 'production'
    process.env.SECRET_KEY = 'backend-secret'
    delete process.env.BACKEND_JWT_SECRET
    delete process.env.JWT_SHARED_SECRET

    expect(() => getJwtVerificationSecretValue()).toThrow(/must set BACKEND_JWT_SECRET or JWT_SHARED_SECRET explicitly/i)
  })

  it('rejects reusing the Supabase service role secret as the shared JWT secret', () => {
    process.env.BACKEND_JWT_SECRET = 'same-secret'
    process.env.SUPABASE_SERVICE_ROLE_KEY = 'same-secret'

    expect(() => getJwtVerificationSecretValue()).toThrow(/different from SUPABASE_SERVICE_ROLE_KEY/i)
  })
})
