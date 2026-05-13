import { randomUUID } from 'crypto'
import { readJournalStore, updateJournalStore } from '@/lib/journalStore'
import { parseNumber, toNullableNumber, toNullableString } from '@/lib/supabase'
import {
  ENTRY_ZONE_PIPS,
  FULL_SL_PIPS,
  TRADE_STATUSES,
  calculateTradeResultEur,
  normalizeTradeStatus,
} from '@/lib/tradeUtils'

const LEGACY_COMPATIBLE_TRADE_INSERT_COLUMNS = new Set([
  'current_price',
  'entry_zone_from',
  'entry_zone_to',
  'entry_zone_pips',
  'total_stop_loss_pips',
  'stop_loss',
  'tp1',
  'tp2',
  'tp3',
  'tp4',
  'feeling',
  'reason_for_entry',
  'satisfaction_emoji',
  'satisfaction_reason',
  'setup_tag',
  'is_favorite',
  'is_mistake',
  'status',
  'profit_loss',
])

function hasSupabaseClient(supabase) {
  return Boolean(supabase?.from)
}

function nowIso() {
  return new Date().toISOString()
}

function rowToTrade(row) {
  if (!row) return null

  const reasonForEntry = row.reason_for_entry ?? row.reasonForEntry ?? row.reason ?? null

  return {
    id: row.id,
    userId: row.user_id ?? row.userId,
    symbol: row.symbol,
    tradeType: row.trade_type ?? row.tradeType,
    entryPrice: row.entry_price ?? row.entryPrice,
    currentPrice: row.current_price ?? row.currentPrice,
    entryZoneFrom: row.entry_zone_from ?? row.entryZoneFrom,
    entryZoneTo: row.entry_zone_to ?? row.entryZoneTo,
    entryZonePips: row.entry_zone_pips ?? row.entryZonePips,
    totalStopLossPips: row.total_stop_loss_pips ?? row.totalStopLossPips,
    lotSize: row.lot_size ?? row.lotSize,
    stopLoss: row.stop_loss ?? row.stopLoss,
    tp1: row.tp1,
    tp2: row.tp2,
    tp3: row.tp3,
    tp4: row.tp4,
    date: row.date,
    feeling: row.feeling,
    reasonForEntry,
    reason: reasonForEntry,
    satisfactionEmoji: row.satisfaction_emoji ?? row.satisfactionEmoji,
    satisfactionReason: row.satisfaction_reason ?? row.satisfactionReason,
    setupTag: row.setup_tag ?? row.setupTag ?? null,
    isFavorite: Boolean(row.is_favorite ?? row.isFavorite),
    isMistake: Boolean(row.is_mistake ?? row.isMistake),
    status: normalizeTradeStatus(row.status),
    profitLoss: row.profit_loss ?? row.profitLoss,
    createdAt: row.created_at ?? row.createdAt,
    updatedAt: row.updated_at ?? row.updatedAt,
  }
}

function toCurrentPrice(value) {
  const numberValue = toNullableNumber(value)
  return numberValue !== null && numberValue > 0 ? numberValue : null
}

function toTradeForCalculation(payload) {
  return {
    symbol: String(payload.symbol || 'XAUUSD').toUpperCase().trim(),
    tradeType: payload.tradeType,
    entryPrice: parseNumber(payload.entryPrice),
    currentPrice: toCurrentPrice(payload.currentPrice),
    lotSize: parseNumber(payload.lotSize),
    status: normalizeTradeStatus(payload.status || 'open'),
  }
}

function toTradeRow(payload, userId, options = {}) {
  const trade = toTradeForCalculation(payload)

  return {
    user_id: userId,
    symbol: trade.symbol,
    trade_type: payload.tradeType,
    date: payload.date,
    status: trade.status,
    entry_price: trade.entryPrice,
    current_price: trade.currentPrice,
    lot_size: trade.lotSize,
    entry_zone_from: toNullableNumber(payload.entryZoneFrom),
    entry_zone_to: toNullableNumber(payload.entryZoneTo),
    entry_zone_pips: toNullableNumber(payload.entryZonePips) ?? ENTRY_ZONE_PIPS,
    total_stop_loss_pips: toNullableNumber(payload.totalStopLossPips) ?? FULL_SL_PIPS,
    stop_loss: toNullableNumber(payload.stopLoss),
    tp1: toNullableNumber(payload.tp1),
    tp2: toNullableNumber(payload.tp2),
    tp3: toNullableNumber(payload.tp3),
    tp4: toNullableNumber(payload.tp4),
    feeling: toNullableString(payload.feeling),
    reason_for_entry: toNullableString(payload.reasonForEntry ?? payload.reason),
    satisfaction_emoji: toNullableString(payload.satisfactionEmoji),
    satisfaction_reason: toNullableString(payload.satisfactionReason),
    setup_tag: toNullableString(payload.setupTag),
    is_favorite: Boolean(payload.isFavorite),
    is_mistake: Boolean(payload.isMistake),
    profit_loss: calculateTradeResultEur({
      ...trade,
      symbol: trade.symbol,
      usdToEurRate: options.usdToEurRate,
    }),
  }
}

function toLocalTrade(payload, userId, options = {}, existingTrade = null) {
  const trade = toTradeForCalculation(payload)
  const timestamp = nowIso()
  const reasonForEntry = toNullableString(payload.reasonForEntry ?? payload.reason)

  return {
    id: existingTrade?.id ?? randomUUID(),
    userId,
    symbol: trade.symbol,
    tradeType: payload.tradeType,
    entryPrice: trade.entryPrice,
    currentPrice: trade.currentPrice,
    entryZoneFrom: toNullableNumber(payload.entryZoneFrom),
    entryZoneTo: toNullableNumber(payload.entryZoneTo),
    entryZonePips: toNullableNumber(payload.entryZonePips) ?? ENTRY_ZONE_PIPS,
    totalStopLossPips: toNullableNumber(payload.totalStopLossPips) ?? FULL_SL_PIPS,
    lotSize: trade.lotSize,
    stopLoss: toNullableNumber(payload.stopLoss),
    tp1: toNullableNumber(payload.tp1),
    tp2: toNullableNumber(payload.tp2),
    tp3: toNullableNumber(payload.tp3),
    tp4: toNullableNumber(payload.tp4),
    date: payload.date,
    feeling: toNullableString(payload.feeling),
    reasonForEntry,
    reason: reasonForEntry,
    satisfactionEmoji: toNullableString(payload.satisfactionEmoji),
    satisfactionReason: toNullableString(payload.satisfactionReason),
    setupTag: toNullableString(payload.setupTag),
    isFavorite: Boolean(payload.isFavorite),
    isMistake: Boolean(payload.isMistake),
    status: trade.status,
    profitLoss: calculateTradeResultEur({
      ...trade,
      symbol: trade.symbol,
      usdToEurRate: options.usdToEurRate,
    }),
    createdAt: existingTrade?.createdAt ?? timestamp,
    updatedAt: timestamp,
  }
}

function sanitizeSearch(value) {
  return String(value || '')
    .trim()
    .replaceAll(',', ' ')
    .replaceAll('%', '')
    .replaceAll('_', '')
}

function parseRequiredPositiveNumber(value, fieldLabel) {
  const parsed = Number(value)

  if (!Number.isFinite(parsed)) {
    return { value: null, error: `${fieldLabel} must be numeric.` }
  }

  if (parsed <= 0) {
    return { value: null, error: `${fieldLabel} must be greater than 0.` }
  }

  return { value: parsed, error: null }
}

function parseOptionalNumber(value, fieldLabel, { allowZero = false } = {}) {
  if (value === '' || value === null || value === undefined) {
    return { value: null, error: null }
  }

  const parsed = Number(value)

  if (!Number.isFinite(parsed)) {
    return { value: null, error: `${fieldLabel} must be numeric.` }
  }

  if (!allowZero && parsed <= 0) {
    return { value: null, error: `${fieldLabel} must be greater than 0.` }
  }

  return { value: parsed, error: null }
}

function validateDirectionalLevels({ tradeType, entryPrice, stopLoss, tp1, tp2, tp3, tp4 }) {
  if (tradeType === 'Buy') {
    if (!(stopLoss < entryPrice)) return 'For Buy trades, stop loss must be lower than entry price.'
    if (!(tp1 > entryPrice)) return 'For Buy trades, TP1 must be higher than entry price.'
    if (!(tp2 > tp1)) return 'For Buy trades, TP2 must be higher than TP1.'
    if (!(tp3 > tp2)) return 'For Buy trades, TP3 must be higher than TP2.'
    if (!(tp4 > tp3)) return 'For Buy trades, TP4 must be higher than TP3.'
    return null
  }

  if (!(stopLoss > entryPrice)) return 'For Sell trades, stop loss must be higher than entry price.'
  if (!(tp1 < entryPrice)) return 'For Sell trades, TP1 must be lower than entry price.'
  if (!(tp2 < tp1)) return 'For Sell trades, TP2 must be lower than TP1.'
  if (!(tp3 < tp2)) return 'For Sell trades, TP3 must be lower than TP2.'
  if (!(tp4 < tp3)) return 'For Sell trades, TP4 must be lower than TP3.'

  return null
}

function compareTradeDates(a, b, ascending = false) {
  const dateCompare = String(a.date || '').localeCompare(String(b.date || ''))
  if (dateCompare !== 0) return ascending ? dateCompare : -dateCompare

  const createdCompare = String(a.createdAt || '').localeCompare(String(b.createdAt || ''))
  return ascending ? createdCompare : -createdCompare
}

function sortLocalTrades(trades, sortBy = 'date-desc') {
  const sorted = [...trades]

  if (sortBy === 'result-desc') {
    return sorted.sort(
      (a, b) =>
        Number(b.profitLoss || 0) - Number(a.profitLoss || 0) ||
        compareTradeDates(a, b)
    )
  }

  if (sortBy === 'result-asc') {
    return sorted.sort(
      (a, b) =>
        Number(a.profitLoss || 0) - Number(b.profitLoss || 0) ||
        compareTradeDates(a, b)
    )
  }

  return sorted.sort((a, b) => compareTradeDates(a, b, sortBy === 'date-asc'))
}

function matchesTradeSearch(trade, search) {
  if (!search) return true

  const haystack = [
    trade.symbol,
    trade.feeling,
    trade.reasonForEntry,
    trade.satisfactionReason,
    trade.setupTag,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

  return haystack.includes(search.toLowerCase())
}

function matchesTradeFilters(trade, filters = {}) {
  const normalizedStatus = normalizeTradeStatus(trade.status)

  if (filters.type && trade.tradeType !== filters.type) return false
  if (filters.status && normalizedStatus !== normalizeTradeStatus(filters.status)) return false
  if (filters.result === 'profit' && !(Number(trade.profitLoss || 0) > 0)) return false
  if (filters.result === 'loss' && !(Number(trade.profitLoss || 0) < 0)) return false
  if (filters.satisfactionEmoji && trade.satisfactionEmoji !== filters.satisfactionEmoji) return false
  if (filters.setupTag && trade.setupTag !== filters.setupTag) return false
  if (filters.marker === 'favorite' && !trade.isFavorite) return false
  if (filters.marker === 'mistake' && !trade.isMistake) return false
  if (filters.date && trade.date !== filters.date) return false
  if (filters.dateFrom && String(trade.date || '') < filters.dateFrom) return false
  if (filters.dateTo && String(trade.date || '') > filters.dateTo) return false

  return matchesTradeSearch(trade, sanitizeSearch(filters.search))
}

function buildTradesQuery(supabase, userId, filters = {}, { legacyMode = false } = {}) {
  let query = supabase.from('trades').select('*').eq('user_id', userId)

  const sortBy = String(filters.sortBy || 'date-desc')

  if (!legacyMode && sortBy === 'date-asc') {
    query = query.order('date', { ascending: true }).order('created_at', { ascending: true })
  } else if (!legacyMode && sortBy === 'result-desc') {
    query = query.order('profit_loss', { ascending: false }).order('date', { ascending: false })
  } else if (!legacyMode && sortBy === 'result-asc') {
    query = query.order('profit_loss', { ascending: true }).order('date', { ascending: false })
  } else {
    query = query.order('date', { ascending: sortBy === 'date-asc' })

    if (!legacyMode) {
      query = query.order('created_at', { ascending: sortBy === 'date-asc' })
    }
  }

  if (filters.type) {
    query = query.eq('trade_type', filters.type)
  }

  if (!legacyMode && filters.status) {
    query = query.eq('status', normalizeTradeStatus(filters.status))
  }

  if (!legacyMode && filters.result === 'profit') {
    query = query.gt('profit_loss', 0)
  }

  if (!legacyMode && filters.result === 'loss') {
    query = query.lt('profit_loss', 0)
  }

  if (!legacyMode && filters.satisfactionEmoji) {
    query = query.eq('satisfaction_emoji', filters.satisfactionEmoji)
  }

  if (!legacyMode && filters.setupTag) {
    query = query.eq('setup_tag', filters.setupTag)
  }

  if (!legacyMode && filters.marker === 'favorite') {
    query = query.eq('is_favorite', true)
  }

  if (!legacyMode && filters.marker === 'mistake') {
    query = query.eq('is_mistake', true)
  }

  if (filters.date) {
    query = query.eq('date', filters.date)
  }

  if (filters.dateFrom) {
    query = query.gte('date', filters.dateFrom)
  }

  if (filters.dateTo) {
    query = query.lte('date', filters.dateTo)
  }

  const search = sanitizeSearch(filters.search)
  if (search) {
    if (legacyMode) {
      query = query.ilike('symbol', `%${search}%`)
    } else {
      query = query.or(
        `symbol.ilike.%${search}%,feeling.ilike.%${search}%,reason_for_entry.ilike.%${search}%`
      )
    }
  }

  return query
}

function getMissingColumnName(error) {
  const haystack = `${String(error?.message || '')}\n${String(error?.details || '')}\n${String(error?.hint || '')}`
  const patterns = [
    /column ["']?(?:public\.)?(?:trades\.)?([a-zA-Z0-9_]+)["']? does not exist/i,
    /Could not find the ['"]([a-zA-Z0-9_]+)['"] column/i,
    /schema cache.*['"]([a-zA-Z0-9_]+)['"]/i,
  ]

  for (const pattern of patterns) {
    const match = haystack.match(pattern)
    if (match?.[1]) return match[1]
  }

  return null
}

export function isMissingColumnError(error, columnName) {
  if (!error) return false

  const haystack = `${String(error.message || '')}\n${String(error.details || '')}\n${String(error.hint || '')}`
  const hasKnownCode = error.code === '42703' || error.code === 'PGRST204'
  const hasKnownText =
    /does not exist/i.test(haystack) ||
    /Could not find the ['"][a-zA-Z0-9_]+['"] column/i.test(haystack)

  if (!hasKnownCode && !hasKnownText) return false
  if (!columnName) return true

  return (
    getMissingColumnName(error) === columnName ||
    haystack.includes(`.${columnName}`) ||
    haystack.includes(`'${columnName}'`) ||
    haystack.includes(`"${columnName}"`) ||
    haystack.includes(` ${columnName} `)
  )
}

export function isTradeSchemaCompatibilityError(error) {
  return isMissingTableError(error, 'trades') || isMissingColumnError(error)
}

export function validateTradePayload(payload) {
  if (!String(payload.symbol || '').trim()) return 'Symbol is required.'
  if (!['Buy', 'Sell'].includes(payload.tradeType)) return 'Trade type must be Buy or Sell.'
  if (!payload.date) return 'Date is required.'

  const normalizedStatus = normalizeTradeStatus(payload.status || 'open')
  if (!TRADE_STATUSES.includes(normalizedStatus)) {
    return 'Invalid status.'
  }

  const entryPriceResult = parseRequiredPositiveNumber(payload.entryPrice, 'Entry price')
  if (entryPriceResult.error) return entryPriceResult.error

  const lotSizeResult = parseRequiredPositiveNumber(payload.lotSize, 'Lot size')
  if (lotSizeResult.error) return lotSizeResult.error

  const currentPriceResult = parseOptionalNumber(payload.currentPrice, 'Current price')
  if (currentPriceResult.error) return currentPriceResult.error

  if (normalizedStatus !== 'open' && currentPriceResult.value === null) {
    return 'Current price is required for closed trades.'
  }

  const entryZoneFromResult = parseRequiredPositiveNumber(payload.entryZoneFrom, 'Entry zone from')
  if (entryZoneFromResult.error) return entryZoneFromResult.error

  const entryZoneToResult = parseRequiredPositiveNumber(payload.entryZoneTo, 'Entry zone to')
  if (entryZoneToResult.error) return entryZoneToResult.error

  if (entryZoneToResult.value < entryZoneFromResult.value) {
    return 'Entry zone to must be greater than or equal to entry zone from.'
  }

  const stopLossResult = parseRequiredPositiveNumber(payload.stopLoss, 'Stop loss')
  if (stopLossResult.error) return stopLossResult.error

  const tp1Result = parseRequiredPositiveNumber(payload.tp1, 'TP1')
  if (tp1Result.error) return tp1Result.error

  const tp2Result = parseRequiredPositiveNumber(payload.tp2, 'TP2')
  if (tp2Result.error) return tp2Result.error

  const tp3Result = parseRequiredPositiveNumber(payload.tp3, 'TP3')
  if (tp3Result.error) return tp3Result.error

  const tp4Result = parseRequiredPositiveNumber(payload.tp4, 'TP4')
  if (tp4Result.error) return tp4Result.error

  const directionalError = validateDirectionalLevels({
    tradeType: payload.tradeType,
    entryPrice: entryPriceResult.value,
    stopLoss: stopLossResult.value,
    tp1: tp1Result.value,
    tp2: tp2Result.value,
    tp3: tp3Result.value,
    tp4: tp4Result.value,
  })

  if (directionalError) return directionalError

  return null
}

export async function listTrades(supabase, userId, filters = {}) {
  if (!hasSupabaseClient(supabase)) {
    const store = await readJournalStore()
    const trades = store.trades
      .map(rowToTrade)
      .filter((trade) => trade.userId === userId && matchesTradeFilters(trade, filters))

    return sortLocalTrades(trades, String(filters.sortBy || 'date-desc'))
  }

  const { data, error } = await buildTradesQuery(supabase, userId, filters)
  if (!error) {
    return (data ?? []).map(rowToTrade)
  }

  if (!isMissingColumnError(error)) {
    throw error
  }

  const fallbackResult = await buildTradesQuery(supabase, userId, filters, { legacyMode: true })
  if (fallbackResult.error) throw fallbackResult.error

  return (fallbackResult.data ?? []).map(rowToTrade)
}

export async function getTradeById(supabase, userId, tradeId) {
  if (!hasSupabaseClient(supabase)) {
    const store = await readJournalStore()
    const trade = store.trades.find((row) => row.id === tradeId && row.userId === userId)
    return rowToTrade(trade)
  }

  const { data, error } = await supabase
    .from('trades')
    .select('*')
    .eq('id', tradeId)
    .eq('user_id', userId)
    .single()

  if (error || !data) return null
  return rowToTrade(data)
}

export async function createTrade(supabase, userId, payload, options = {}) {
  if (!hasSupabaseClient(supabase)) {
    const trade = toLocalTrade(payload, userId, options)
    await updateJournalStore((store) => {
      store.trades.push(trade)
      return store
    })
    return trade
  }

  const row = toTradeRow(payload, userId, options)
  const insertRow = { ...row }
  const maxAttempts = Object.keys(insertRow).length

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const { data, error } = await supabase
      .from('trades')
      .insert(insertRow)
      .select('*')
      .single()

    if (!error) return rowToTrade(data)

    const missingColumn = getMissingColumnName(error)
    if (!missingColumn || !LEGACY_COMPATIBLE_TRADE_INSERT_COLUMNS.has(missingColumn) || !(missingColumn in insertRow)) {
      throw error
    }

    delete insertRow[missingColumn]
  }

  throw new Error('Unable to create trade with the current trades schema.')
}

export async function updateTrade(supabase, userId, tradeId, payload, options = {}) {
  if (!hasSupabaseClient(supabase)) {
    let updatedTrade = null

    await updateJournalStore((store) => {
      const index = store.trades.findIndex((row) => row.id === tradeId && row.userId === userId)
      if (index === -1) return store

      updatedTrade = toLocalTrade(payload, userId, options, rowToTrade(store.trades[index]))
      store.trades[index] = updatedTrade
      return store
    })

    return updatedTrade
  }

  const existing = await getTradeById(supabase, userId, tradeId)
  if (!existing) return null

  const updates = toTradeRow(payload, userId, options)
  delete updates.user_id

  const updateRow = { ...updates }
  const maxAttempts = Object.keys(updateRow).length

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const { error } = await supabase
      .from('trades')
      .update(updateRow)
      .eq('id', tradeId)
      .eq('user_id', userId)

    if (!error) {
      return getTradeById(supabase, userId, tradeId)
    }

    const missingColumn = getMissingColumnName(error)
    if (!missingColumn || !LEGACY_COMPATIBLE_TRADE_INSERT_COLUMNS.has(missingColumn) || !(missingColumn in updateRow)) {
      throw error
    }

    delete updateRow[missingColumn]
  }

  throw new Error('Unable to update trade with the current trades schema.')
}

export async function deleteTrade(supabase, userId, tradeId) {
  if (!hasSupabaseClient(supabase)) {
    await updateJournalStore((store) => {
      store.trades = store.trades.filter((row) => !(row.id === tradeId && row.userId === userId))
      return store
    })
    return
  }

  const { error } = await supabase
    .from('trades')
    .delete()
    .eq('id', tradeId)
    .eq('user_id', userId)

  if (error) throw error
}

export function isMissingTableError(error, tableName) {
  if (!error) return false
  const isMissingCode = error.code === '42P01' || error.code === 'PGRST205'
  if (!isMissingCode) return false
  if (!tableName) return true
  const msg = String(error.message || '')
  return (
    msg.includes(`"public.${tableName}"`) ||
    msg.includes(`'public.${tableName}'`) ||
    msg.includes(tableName)
  )
}

function rowToProfile(row, user) {
  const fallbackName = user?.user_metadata?.display_name || user?.email?.split('@')[0] || ''
  const fallbackLanguage = user?.user_metadata?.language || 'nl'
  const fallbackCurrency = user?.user_metadata?.preferred_currency || user?.user_metadata?.currency || 'EUR'
  const currency = row?.preferred_currency ?? row?.preferredCurrency ?? row?.currency ?? fallbackCurrency

  return {
    userId: user?.id ?? row?.user_id ?? row?.userId ?? null,
    email: row?.email ?? user?.email ?? '',
    displayName: row?.display_name ?? row?.displayName ?? fallbackName,
    language: row?.language ?? fallbackLanguage,
    currency,
    preferredCurrency: currency,
    usdToEurRate: row?.usd_to_eur_rate ?? row?.usdToEurRate ?? null,
    avatarUrl: row?.avatar_url ?? row?.avatarUrl ?? null,
    accountBalance: row?.account_balance ?? row?.accountBalance ?? null,
    ftmoAccountSize: row?.ftmo_account_size ?? row?.ftmoAccountSize ?? null,
    dailyLossLimit: row?.daily_loss_limit ?? row?.dailyLossLimit ?? null,
    maxLossLimit: row?.max_loss_limit ?? row?.maxLossLimit ?? null,
    maxTradesPerDay: row?.max_trades_per_day ?? row?.maxTradesPerDay ?? null,
    maxRiskPerDay: row?.max_risk_per_day ?? row?.maxRiskPerDay ?? null,
    dailyProfitTarget: row?.daily_profit_target ?? row?.dailyProfitTarget ?? null,
    createdAt: row?.created_at ?? row?.createdAt ?? null,
    updatedAt: row?.updated_at ?? row?.updatedAt ?? null,
    migrationMissing: false,
  }
}

export async function getProfile(supabase, userId, fallbackUser = null) {
  if (!hasSupabaseClient(supabase)) {
    const store = await readJournalStore()
    return rowToProfile(store.profiles[userId] ?? null, fallbackUser)
  }

  const { data, error } = await supabase.from('profiles').select('*').eq('user_id', userId).single()

  if (error && error.code !== 'PGRST116' && !isMissingTableError(error, 'profiles')) {
    throw error
  }

  if (isMissingTableError(error, 'profiles')) {
    return {
      ...rowToProfile(null, fallbackUser),
      migrationMissing: true,
    }
  }

  return rowToProfile(data, fallbackUser)
}

export async function upsertProfile(supabase, userId, payload) {
  if (!hasSupabaseClient(supabase)) {
    let profile = null

    await updateJournalStore((store) => {
      const current = rowToProfile(store.profiles[userId] ?? null, null)
      profile = {
        ...current,
        userId,
        ...(Object.prototype.hasOwnProperty.call(payload, 'displayName') ? { displayName: toNullableString(payload.displayName) || current.displayName } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'language') ? { language: toNullableString(payload.language) || 'nl' } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'currency') ? { currency: toNullableString(payload.currency) || 'EUR' } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'preferredCurrency') ? { preferredCurrency: toNullableString(payload.preferredCurrency) || 'EUR' } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'usdToEurRate') ? { usdToEurRate: Number(payload.usdToEurRate) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'avatarUrl') ? { avatarUrl: toNullableString(payload.avatarUrl) } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'accountBalance') ? { accountBalance: Number(payload.accountBalance) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'ftmoAccountSize') ? { ftmoAccountSize: Number(payload.ftmoAccountSize) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'dailyLossLimit') ? { dailyLossLimit: Number(payload.dailyLossLimit) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'maxLossLimit') ? { maxLossLimit: Number(payload.maxLossLimit) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'maxTradesPerDay') ? { maxTradesPerDay: Number(payload.maxTradesPerDay) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'maxRiskPerDay') ? { maxRiskPerDay: Number(payload.maxRiskPerDay) || null } : {}),
        ...(Object.prototype.hasOwnProperty.call(payload, 'dailyProfitTarget') ? { dailyProfitTarget: Number(payload.dailyProfitTarget) || null } : {}),
        createdAt: current.createdAt ?? nowIso(),
        updatedAt: nowIso(),
        migrationMissing: false,
      }

      if (!Object.prototype.hasOwnProperty.call(payload, 'preferredCurrency') && Object.prototype.hasOwnProperty.call(payload, 'currency')) {
        profile.preferredCurrency = profile.currency
      }

      if (!Object.prototype.hasOwnProperty.call(payload, 'currency') && Object.prototype.hasOwnProperty.call(payload, 'preferredCurrency')) {
        profile.currency = profile.preferredCurrency
      }

      store.profiles[userId] = profile
      return store
    })

    return profile
  }

  const updates = { user_id: userId }

  if ('displayName' in payload) {
    updates.display_name = toNullableString(payload.displayName)
  }

  if ('language' in payload) {
    updates.language = toNullableString(payload.language) || 'nl'
  }

  if ('currency' in payload) {
    updates.currency = toNullableString(payload.currency) || 'EUR'
    updates.preferred_currency = updates.currency
  }

  if ('preferredCurrency' in payload) {
    updates.preferred_currency = toNullableString(payload.preferredCurrency) || 'EUR'
    updates.currency = updates.preferred_currency
  }

  if ('usdToEurRate' in payload) {
    updates.usd_to_eur_rate = Number(payload.usdToEurRate) || null
  }

  if ('avatarUrl' in payload) {
    updates.avatar_url = toNullableString(payload.avatarUrl)
  }

  if ('accountBalance' in payload) {
    updates.account_balance = Number(payload.accountBalance) || null
  }

  if ('ftmoAccountSize' in payload) {
    updates.ftmo_account_size = Number(payload.ftmoAccountSize) || null
  }

  if ('dailyLossLimit' in payload) {
    updates.daily_loss_limit = Number(payload.dailyLossLimit) || null
  }

  if ('maxLossLimit' in payload) {
    updates.max_loss_limit = Number(payload.maxLossLimit) || null
  }

  if ('maxTradesPerDay' in payload) {
    updates.max_trades_per_day = Number(payload.maxTradesPerDay) || null
  }

  if ('maxRiskPerDay' in payload) {
    updates.max_risk_per_day = Number(payload.maxRiskPerDay) || null
  }

  if ('dailyProfitTarget' in payload) {
    updates.daily_profit_target = Number(payload.dailyProfitTarget) || null
  }

  for (const key of Object.keys(updates)) {
    if (updates[key] === undefined) delete updates[key]
  }

  const { data: rows, error } = await supabase
    .from('profiles')
    .upsert(updates, { onConflict: 'user_id' })
    .select('*')

  if (error) throw error
  return rowToProfile(rows?.[0] ?? null)
}
