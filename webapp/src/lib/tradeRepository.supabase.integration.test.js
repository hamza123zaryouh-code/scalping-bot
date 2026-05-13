import path from 'path'
import { fileURLToPath } from 'url'
import { config as loadDotenv } from 'dotenv'
import { beforeAll, afterAll, describe, expect, it } from 'vitest'
import {
  buildAppUser,
  createSupabaseServiceClient,
  ensureSupabaseAppUser,
} from './supabase'
import {
  createTrade,
  deleteTrade,
  getProfile,
  getTradeById,
  listTrades,
  updateTrade,
  upsertProfile,
} from './tradeRepository'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

loadDotenv({ path: path.resolve(__dirname, '../../../.env') })
loadDotenv({ path: path.resolve(__dirname, '../../.env.local'), override: false })

const shouldRunIntegration =
  process.env.RUN_SUPABASE_INTEGRATION === 'true' &&
  process.env.NEXT_PUBLIC_SUPABASE_URL &&
  process.env.SUPABASE_SERVICE_ROLE_KEY

const describeIf = shouldRunIntegration ? describe : describe.skip

const tradePayload = {
  symbol: 'XAUUSD',
  tradeType: 'Buy',
  date: '2026-05-13',
  entryPrice: 2300,
  currentPrice: 2310,
  entryZoneFrom: 2298,
  entryZoneTo: 2302,
  lotSize: 0.1,
  stopLoss: 2290,
  tp1: 2310,
  tp2: 2320,
  tp3: 2330,
  tp4: 2340,
  status: 'TP hit',
  reasonForEntry: 'Supabase integration check',
}

describeIf('tradeRepository live Supabase integration', () => {
  let supabase
  let user
  const runId = Date.now()

  beforeAll(async () => {
    supabase = createSupabaseServiceClient()
    user = buildAppUser({
      sub: `supabase-int-${runId}`,
      role: 'admin',
      email: `supabase-int-${runId}@local.invalid`,
      name: 'Supabase Integration',
    })

    await ensureSupabaseAppUser(supabase, user)
  })

  afterAll(async () => {
    if (!supabase || !user) return

    await supabase.from('trades').delete().eq('user_id', user.id)
    await supabase.from('reviews').delete().eq('user_id', user.id)
    await supabase.from('profiles').delete().eq('user_id', user.id)
    await supabase.from('app_users').delete().eq('id', user.id)
  })

  it('runs profile and trade CRUD against the real Supabase schema', async () => {
    const initialProfile = await getProfile(supabase, user.id, user)
    expect(initialProfile.userId).toBe(user.id)

    const updatedProfile = await upsertProfile(supabase, user.id, {
      displayName: 'Supabase Integration User',
      preferredCurrency: 'USD',
      dailyLossLimit: 500,
      maxLossLimit: 1000,
    })

    expect(updatedProfile.displayName).toBe('Supabase Integration User')
    expect(updatedProfile.preferredCurrency).toBe('USD')

    const createdTrade = await createTrade(supabase, user.id, tradePayload, { usdToEurRate: 0.92 })

    expect(createdTrade.id).toBeTruthy()
    expect(createdTrade.userId).toBe(user.id)

    const listedTrades = await listTrades(supabase, user.id)
    expect(listedTrades.some((trade) => trade.id === createdTrade.id)).toBe(true)

    const updatedTrade = await updateTrade(supabase, user.id, createdTrade.id, {
      ...tradePayload,
      currentPrice: 2335,
      status: 'manually closed',
      satisfactionReason: 'Integration update',
    })

    expect(updatedTrade.currentPrice).toBe(2335)
    expect(updatedTrade.status).toBe('manually closed')

    const fetchedTrade = await getTradeById(supabase, user.id, createdTrade.id)
    expect(fetchedTrade?.id).toBe(createdTrade.id)
    expect(fetchedTrade?.satisfactionReason).toBe('Integration update')

    await deleteTrade(supabase, user.id, createdTrade.id)

    const afterDelete = await listTrades(supabase, user.id)
    expect(afterDelete.find((trade) => trade.id === createdTrade.id)).toBeUndefined()
  })
})
