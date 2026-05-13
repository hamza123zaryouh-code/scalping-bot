import { beforeEach, describe, expect, it, vi } from 'vitest'

let mockStore

vi.mock('./journalStore', () => ({
  readJournalStore: vi.fn(async () => JSON.parse(JSON.stringify(mockStore))),
  updateJournalStore: vi.fn(async (mutator) => {
    const workingCopy = JSON.parse(JSON.stringify(mockStore))
    const nextStore = (await mutator(workingCopy)) ?? workingCopy
    mockStore = JSON.parse(JSON.stringify(nextStore))
    return nextStore
  }),
}))

import {
  createTrade,
  deleteTrade,
  getProfile,
  getTradeById,
  listTrades,
  updateTrade,
  upsertProfile,
} from './tradeRepository'

function createMemorySupabase() {
  const state = {
    app_users: [],
    profiles: [],
    trades: [],
  }

  const clone = (value) => JSON.parse(JSON.stringify(value))

  class QueryBuilder {
    constructor(table) {
      this.table = table
      this.operation = 'select'
      this.filters = []
      this.orders = []
      this.payload = null
      this.singleResult = false
      this.onConflict = null
    }

    select() {
      return this
    }

    eq(field, value) {
      this.filters.push((row) => row[field] === value)
      return this
    }

    gte(field, value) {
      this.filters.push((row) => row[field] >= value)
      return this
    }

    lte(field, value) {
      this.filters.push((row) => row[field] <= value)
      return this
    }

    gt(field, value) {
      this.filters.push((row) => row[field] > value)
      return this
    }

    lt(field, value) {
      this.filters.push((row) => row[field] < value)
      return this
    }

    order(field, { ascending = false } = {}) {
      this.orders.push({ field, ascending })
      return this
    }

    or() {
      return this
    }

    ilike() {
      return this
    }

    insert(payload) {
      this.operation = 'insert'
      this.payload = clone(payload)
      return this
    }

    update(payload) {
      this.operation = 'update'
      this.payload = clone(payload)
      return this
    }

    delete() {
      this.operation = 'delete'
      return this
    }

    upsert(payload, { onConflict } = {}) {
      this.operation = 'upsert'
      this.payload = clone(payload)
      this.onConflict = onConflict
      return this
    }

    single() {
      this.singleResult = true
      return Promise.resolve(this.execute())
    }

    then(resolve, reject) {
      return Promise.resolve(this.execute()).then(resolve, reject)
    }

    execute() {
      const rows = state[this.table]

      if (this.operation === 'insert') {
        const row = clone(this.payload)
        row.id = row.id || `row-${rows.length + 1}`
        rows.push(row)
        return { data: this.singleResult ? clone(row) : [clone(row)], error: null }
      }

      if (this.operation === 'update') {
        let updatedRow = null
        for (const row of rows) {
          if (this.filters.every((predicate) => predicate(row))) {
            Object.assign(row, clone(this.payload))
            updatedRow = clone(row)
          }
        }
        return { data: updatedRow, error: null }
      }

      if (this.operation === 'delete') {
        const kept = rows.filter((row) => !this.filters.every((predicate) => predicate(row)))
        state[this.table] = kept
        return { data: null, error: null }
      }

      if (this.operation === 'upsert') {
        const payload = clone(this.payload)
        const conflictField = this.onConflict || 'id'
        const existing = rows.find((row) => row[conflictField] === payload[conflictField])
        if (existing) {
          Object.assign(existing, payload)
        } else {
          rows.push(payload)
        }
        const row = existing || payload
        return { data: [clone(row)], error: null }
      }

      let result = rows.filter((row) => this.filters.every((predicate) => predicate(row)))
      for (const { field, ascending } of this.orders.slice().reverse()) {
        result = result.slice().sort((a, b) => {
          if (a[field] === b[field]) return 0
          return a[field] > b[field] ? (ascending ? 1 : -1) : (ascending ? -1 : 1)
        })
      }

      if (this.singleResult) {
        const row = result[0] ?? null
        if (!row) {
          return { data: null, error: { code: 'PGRST116', message: 'Not found' } }
        }
        return { data: clone(row), error: null }
      }

      return { data: clone(result), error: null }
    }
  }

  return {
    state,
    from(table) {
      return new QueryBuilder(table)
    },
  }
}

const basePayload = {
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
  reasonForEntry: 'Breakout',
}

beforeEach(() => {
  mockStore = { profiles: {}, trades: [], reviews: [] }
})

describe('tradeRepository local persistence', () => {
  it('creates, lists, updates and deletes trades locally', async () => {
    const created = await createTrade(null, 'user-local', basePayload, { usdToEurRate: 0.92 })
    expect(created.id).toBeTruthy()

    const listed = await listTrades(null, 'user-local')
    expect(listed).toHaveLength(1)

    const updated = await updateTrade(null, 'user-local', created.id, {
      ...basePayload,
      currentPrice: 2320,
    })
    expect(updated.currentPrice).toBe(2320)

    const fetched = await getTradeById(null, 'user-local', created.id)
    expect(fetched.id).toBe(created.id)

    await deleteTrade(null, 'user-local', created.id)
    const afterDelete = await listTrades(null, 'user-local')
    expect(afterDelete).toEqual([])
  })

  it('reads and updates a local profile', async () => {
    const initial = await getProfile(null, 'user-local', {
      id: 'user-local',
      email: 'user@example.com',
      user_metadata: { display_name: 'Desk User', language: 'en', currency: 'USD' },
    })
    expect(initial.displayName).toBe('Desk User')

    const updated = await upsertProfile(null, 'user-local', {
      displayName: 'Updated User',
      preferredCurrency: 'EUR',
    })

    expect(updated.displayName).toBe('Updated User')
    expect(updated.preferredCurrency).toBe('EUR')
  })
})

describe('tradeRepository Supabase persistence', () => {
  it('creates, lists, updates and deletes trades in Supabase mode', async () => {
    const supabase = createMemorySupabase()

    const created = await createTrade(supabase, 'user-supabase', basePayload, { usdToEurRate: 0.92 })
    expect(created.id).toBeTruthy()

    const listed = await listTrades(supabase, 'user-supabase')
    expect(listed).toHaveLength(1)

    const updated = await updateTrade(supabase, 'user-supabase', created.id, {
      ...basePayload,
      currentPrice: 2330,
    })
    expect(updated.currentPrice).toBe(2330)

    await deleteTrade(supabase, 'user-supabase', created.id)
    const afterDelete = await listTrades(supabase, 'user-supabase')
    expect(afterDelete).toEqual([])
  })

  it('reads and updates profiles in Supabase mode', async () => {
    const supabase = createMemorySupabase()

    await upsertProfile(supabase, 'user-supabase', {
      displayName: 'Supabase User',
      preferredCurrency: 'USD',
    })

    const profile = await getProfile(supabase, 'user-supabase', {
      id: 'user-supabase',
      email: 'supabase@example.com',
      user_metadata: { display_name: 'Supabase User', currency: 'USD' },
    })

    expect(profile.displayName).toBe('Supabase User')
    expect(profile.preferredCurrency).toBe('USD')
  })
})
