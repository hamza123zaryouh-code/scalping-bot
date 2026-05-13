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

function rowToTrade(row) {
  if (!row) return null

  const reasonForEntry = row.reason_for_entry ?? row.reason ?? null

  return {
    id: row.id,
    userId: row.user_id,
    symbol: row.symbol,
    tradeType: row.trade_type,
    entryPrice: row.entry_price,
    currentPrice: row.current_price,
    entryZoneFrom: row.entry_zone_from,
    entryZoneTo: row.entry_zone_to,
    entryZonePips: row.entry_zone_pips,
    totalStopLossPips: row.total_stop_loss_pips,
    lotSize: row.lot_size,
    stopLoss: row.stop_loss,
    tp1: row.tp1,
    tp2: row.tp2,
    tp3: row.tp3,
    tp4: row.tp4,
    date: row.date,
    feeling: row.feeling,
    reasonForEntry,
    reason: reasonForEntry,
    satisfactionEmoji: row.satisfaction_emoji,
    satisfactionReason: row.satisfaction_reason,
    setupTag: row.setup_tag ?? null,
    isFavorite: Boolean(row.is_favorite),
    isMistake: Boolean(row.is_mistake),
    status: normalizeTradeStatus(row.status),
    profitLoss: row.profit_loss,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
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
  return (
    isMissingTableError(error, 'trades') ||
    isMissingColumnError(error)
  )
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
  const { error } = await supabase
    .from('trades')
    .delete()
    .eq('id', tradeId)
    .eq('user_id', userId)

  if (error) throw error
}

export function isMissingTableError(error, tableName) {
  if (!error) return false
  // 42P01 = PostgreSQL undefined_table; PGRST205 = PostgREST relationship not found
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
  const currency = row?.preferred_currency ?? row?.currency ?? fallbackCurrency

  return {
    userId: user?.id ?? row?.user_id ?? null,
    email: user?.email ?? '',
    displayName: row?.display_name ?? fallbackName,
    language: row?.language ?? fallbackLanguage,
    currency,
    preferredCurrency: currency,
    usdToEurRate: row?.usd_to_eur_rate ?? null,
    avatarUrl: row?.avatar_url ?? null,
    accountBalance: row?.account_balance ?? null,
    ftmoAccountSize: row?.ftmo_account_size ?? null,
    dailyLossLimit: row?.daily_loss_limit ?? null,
    maxLossLimit: row?.max_loss_limit ?? null,
    maxTradesPerDay: row?.max_trades_per_day ?? null,
    maxRiskPerDay: row?.max_risk_per_day ?? null,
    dailyProfitTarget: row?.daily_profit_target ?? null,
    createdAt: row?.created_at ?? null,
    updatedAt: row?.updated_at ?? null,
    migrationMissing: false,
  }
}

export async function getProfile(supabase, userId, fallbackUser = null) {
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

  // Remove undefined keys so we don't accidentally null out columns we didn't intend to touch
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
