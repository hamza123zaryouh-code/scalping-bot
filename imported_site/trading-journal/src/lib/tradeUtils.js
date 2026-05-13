import { getSymbolConfig } from '@/lib/symbolConfig'
import {
  USD_TO_EUR_RATE,
  convertCurrency,
  convertFromEur,
  convertToEur,
  getUsdToEurRate,
} from '@/lib/currencyConfig'

export const ENTRY_ZONE_PIPS = 30
export const FULL_SL_PIPS = 60
export const ENTRY_TOLERANCE_PIPS = 30
export const REAL_STOP_PIPS = 30
export const TP_LEVEL_COUNT = 4

export const TRADE_STATUSES = [
  'open',
  'closed profit',
  'closed loss',
  'SL hit',
  'TP hit',
  'manually closed',
]

const LEGACY_STATUS_MAP = {
  closed: 'manually closed',
  closed_profit: 'closed profit',
  closed_loss: 'closed loss',
  sl_hit: 'SL hit',
  hit_sl: 'SL hit',
  tp_hit: 'TP hit',
  hit_tp: 'TP hit',
  manually_closed: 'manually closed',
}

export const SATISFACTION_EMOJIS = ['😄', '🙂', '😐', '😞', '😡']

export const SETUP_TAGS = [
  'Breakout',
  'Retest',
  'Support/Resistance',
  'EMA',
  'RSI',
  'Liquidity',
  'Other',
]

export function getPreferredCurrency(profile) {
  return String(profile?.preferredCurrency || profile?.currency || 'EUR').toUpperCase()
}

export function getProfileUsdToEurRate(profile) {
  return getUsdToEurRate(profile?.usdToEurRate)
}

export function usesIndicativeFx(profile) {
  return getPreferredCurrency(profile) !== 'EUR' && !Number(profile?.usdToEurRate)
}

export function convertStoredEurToProfileCurrency(value, profile) {
  return convertFromEur(value, getPreferredCurrency(profile), getProfileUsdToEurRate(profile))
}

export function tradesWithProfileCurrency(trades, profile) {
  return trades.map((trade) => ({
    ...trade,
    profitLoss: convertStoredEurToProfileCurrency(trade.profitLoss, profile),
    profitLossEur: Number(trade.profitLoss || 0),
  }))
}

function toFiniteNumber(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function isPositiveFinite(value) {
  const parsed = toFiniteNumber(value)
  return parsed !== null && parsed > 0
}

export function normalizeTradeStatus(status) {
  const raw = String(status || '').trim()

  if (TRADE_STATUSES.includes(raw)) return raw

  const lowerRaw = raw.toLowerCase()
  if (lowerRaw in LEGACY_STATUS_MAP) return LEGACY_STATUS_MAP[lowerRaw]

  return 'open'
}

export function isClosedTradeStatus(status) {
  return normalizeTradeStatus(status) !== 'open'
}

export function canCalculateTradeResult({ entryPrice, currentPrice, lotSize }) {
  return (
    isPositiveFinite(entryPrice) &&
    isPositiveFinite(currentPrice) &&
    isPositiveFinite(lotSize)
  )
}

export function calculateProfitLossEur({
  tradeType,
  entryPrice,
  currentPrice,
  lotSize,
  symbol = 'XAUUSD',
  usdToEurRate = USD_TO_EUR_RATE,
}) {
  if (!canCalculateTradeResult({ entryPrice, currentPrice, lotSize })) return 0

  const entry = Number(entryPrice)
  const current = Number(currentPrice)
  const lot = Number(lotSize)

  const { contractSize, profitCurrency } = getSymbolConfig(symbol)
  const move = tradeType === 'Sell' ? entry - current : current - entry
  const profitInProfitCurrency = move * lot * contractSize

  return convertToEur(profitInProfitCurrency, profitCurrency, usdToEurRate)
}

export function calculateProfitLossInCurrency({
  tradeType,
  entryPrice,
  currentPrice,
  lotSize,
  symbol = 'XAUUSD',
  currency = 'EUR',
  usdToEurRate = USD_TO_EUR_RATE,
}) {
  if (!canCalculateTradeResult({ entryPrice, currentPrice, lotSize })) return 0

  const entry = Number(entryPrice)
  const current = Number(currentPrice)
  const lot = Number(lotSize)

  const { contractSize, profitCurrency } = getSymbolConfig(symbol)
  const move = tradeType === 'Sell' ? entry - current : current - entry
  const profitInProfitCurrency = move * lot * contractSize

  return convertCurrency(profitInProfitCurrency, profitCurrency, currency, usdToEurRate)
}

export function calculateTradeResultEur(trade) {
  return calculateProfitLossEur({
    tradeType: trade.tradeType,
    entryPrice: trade.entryPrice,
    currentPrice: trade.currentPrice,
    lotSize: trade.lotSize,
    symbol: trade.symbol ?? 'XAUUSD',
    usdToEurRate: trade.usdToEurRate ?? USD_TO_EUR_RATE,
  })
}

export function formatCurrency(value, currency = 'EUR') {
  const amount = Number(value || 0)
  const sign = amount > 0 ? '+' : amount < 0 ? '-' : ''

  const formatted = new Intl.NumberFormat('nl-NL', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(amount))

  return `${sign}${formatted}`
}

export function getStatusLabelKey(status) {
  switch (normalizeTradeStatus(status)) {
    case 'open':
      return 'status.open'
    case 'closed profit':
      return 'status.closedProfit'
    case 'closed loss':
      return 'status.closedLoss'
    case 'SL hit':
      return 'status.slHit'
    case 'TP hit':
      return 'status.tpHit'
    case 'manually closed':
      return 'status.manuallyClosed'
    default:
      return 'status.open'
  }
}

function getMondayOfWeek(date) {
  const d = new Date(date)
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  return d.toISOString().slice(0, 10)
}

export function buildDashboardStats(trades) {
  const today = new Date()
  const todayKey = today.toISOString().slice(0, 10)
  const weekStartKey = getMondayOfWeek(today)
  const monthStartKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`

  const totalTrades = trades.length
  const openTrades = trades.filter((trade) => normalizeTradeStatus(trade.status) === 'open').length
  const closedTrades = trades.filter((trade) => normalizeTradeStatus(trade.status) !== 'open').length
  const totalProfitLoss = trades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)

  const profitLossToday = trades
    .filter((trade) => trade.date === todayKey)
    .reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)

  const profitLossWeek = trades
    .filter((trade) => trade.date >= weekStartKey)
    .reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)

  const profitLossMonth = trades
    .filter((trade) => trade.date >= monthStartKey)
    .reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)

  const finishedTrades = trades.filter((trade) => normalizeTradeStatus(trade.status) !== 'open')
  const winningTrades = finishedTrades.filter((trade) => Number(trade.profitLoss || 0) > 0)
  const losingTrades = finishedTrades.filter((trade) => Number(trade.profitLoss || 0) < 0)

  const winRate =
    finishedTrades.length > 0
      ? Math.round((winningTrades.length / finishedTrades.length) * 100)
      : 0

  const avgWin =
    winningTrades.length > 0
      ? winningTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0) /
        winningTrades.length
      : 0

  const avgLoss =
    losingTrades.length > 0
      ? losingTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0) /
        losingTrades.length
      : 0

  const bestTrade =
    trades.length > 0
      ? trades.reduce((best, trade) =>
          Number(trade.profitLoss || 0) > Number(best.profitLoss || 0) ? trade : best
        )
      : null

  const worstTrade =
    trades.length > 0
      ? trades.reduce((worst, trade) =>
          Number(trade.profitLoss || 0) < Number(worst.profitLoss || 0) ? trade : worst
        )
      : null

  return {
    totalTrades,
    openTrades,
    closedTrades,
    totalProfitLoss,
    profitLossToday,
    profitLossWeek,
    profitLossMonth,
    winRate,
    avgWin,
    avgLoss,
    winningTrades: winningTrades.length,
    losingTrades: losingTrades.length,
    bestTrade,
    worstTrade,
  }
}

export function buildStatistics(trades) {
  const totalTrades = trades.length

  const openTrades = trades.filter((trade) => normalizeTradeStatus(trade.status) === 'open').length
  const closedTrades = trades.filter((trade) => normalizeTradeStatus(trade.status) !== 'open').length

  const winningTrades = trades.filter((trade) => Number(trade.profitLoss || 0) > 0)
  const losingTrades = trades.filter((trade) => Number(trade.profitLoss || 0) < 0)

  const totalProfitLoss = trades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)
  const totalWins = winningTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)
  const totalLossesAbs = Math.abs(
    losingTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0)
  )

  const winRate = closedTrades > 0 ? Math.round((winningTrades.length / closedTrades) * 100) : 0

  const avgWin = winningTrades.length > 0 ? totalWins / winningTrades.length : 0

  const avgLoss =
    losingTrades.length > 0
      ? losingTrades.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0) /
        losingTrades.length
      : 0

  const profitFactor = totalLossesAbs > 0 ? totalWins / totalLossesAbs : null

  const bestTrade =
    trades.length > 0
      ? trades.reduce((best, trade) =>
          Number(trade.profitLoss || 0) > Number(best.profitLoss || 0) ? trade : best
        )
      : null

  const worstTrade =
    trades.length > 0
      ? trades.reduce((worst, trade) =>
          Number(trade.profitLoss || 0) < Number(worst.profitLoss || 0) ? trade : worst
        )
      : null

  const buyCount = trades.filter((trade) => trade.tradeType === 'Buy').length
  const sellCount = trades.filter((trade) => trade.tradeType === 'Sell').length

  const byDay = {}
  for (const trade of trades) {
    if (!byDay[trade.date]) byDay[trade.date] = 0
    byDay[trade.date] += Number(trade.profitLoss || 0)
  }

  const dayEntries = Object.entries(byDay)

  let bestDay = null
  let worstDay = null

  if (dayEntries.length > 0) {
    const [bestDate, bestPnl] = dayEntries.reduce((best, entry) => (entry[1] > best[1] ? entry : best))
    const [worstDate, worstPnl] = dayEntries.reduce((worst, entry) =>
      entry[1] < worst[1] ? entry : worst
    )

    bestDay = { date: bestDate, pnl: bestPnl }
    worstDay = { date: worstDate, pnl: worstPnl }
  }

  return {
    totalTrades,
    openTrades,
    closedTrades,
    winningTrades: winningTrades.length,
    losingTrades: losingTrades.length,
    winRate,
    totalProfitLoss,
    avgWin,
    avgLoss,
    profitFactor,
    bestTrade,
    worstTrade,
    buyCount,
    sellCount,
    bestDay,
    worstDay,
  }
}

export function buildEmojiSummary(trades) {
  const summary = {}

  for (const emoji of SATISFACTION_EMOJIS) {
    summary[emoji] = 0
  }

  for (const trade of trades) {
    const emoji = trade.satisfactionEmoji
    if (emoji && Object.prototype.hasOwnProperty.call(summary, emoji)) {
      summary[emoji] += 1
    }
  }

  return summary
}

export function buildAgendaSummary(trades, limit = 6) {
  const buckets = {}

  for (const trade of trades) {
    if (!trade?.date) continue

    if (!buckets[trade.date]) {
      buckets[trade.date] = {
        date: trade.date,
        tradeCount: 0,
        totalProfitLoss: 0,
      }
    }

    buckets[trade.date].tradeCount += 1
    buckets[trade.date].totalProfitLoss += Number(trade.profitLoss || 0)
  }

  return Object.values(buckets)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, limit)
}

export function formatEntryZone(from, to) {
  const zoneFrom = toFiniteNumber(from)
  const zoneTo = toFiniteNumber(to)

  const hasFrom = zoneFrom !== null && zoneFrom > 0
  const hasTo = zoneTo !== null && zoneTo > 0

  if (hasFrom && hasTo) return `${zoneFrom} - ${zoneTo}`
  if (hasFrom) return String(zoneFrom)
  if (hasTo) return String(zoneTo)
  return null
}

export function calculateTradeRisk(trade, accountBalance, options = {}) {
  const entry = Number(trade.entryPrice)
  const sl = Number(trade.stopLoss)
  const lot = Number(trade.lotSize)

  if (!entry || !sl || !lot) return null

  const { contractSize, profitCurrency } = getSymbolConfig(trade.symbol || 'XAUUSD')
  const targetCurrency = String(options.currency || 'EUR').toUpperCase()
  const usdToEurRate = getUsdToEurRate(options.usdToEurRate)
  const riskInProfitCurrency = Math.abs(entry - sl) * lot * contractSize
  const riskEur = convertToEur(riskInProfitCurrency, profitCurrency, usdToEurRate)
  const riskAmount = convertCurrency(
    riskInProfitCurrency,
    profitCurrency,
    targetCurrency,
    usdToEurRate
  )
  const balance = Number(accountBalance)
  const riskPercent = balance > 0 ? (riskAmount / balance) * 100 : null

  return { riskEur, riskAmount, riskPercent, currency: targetCurrency }
}

export function calculateTradeRewardForTarget(trade, targetKey, options = {}) {
  const entry = Number(trade.entryPrice)
  const target = Number(trade[targetKey])
  const lot = Number(trade.lotSize)

  if (!entry || !target || !lot) return null

  const { contractSize, profitCurrency } = getSymbolConfig(trade.symbol || 'XAUUSD')
  const targetCurrency = String(options.currency || 'EUR').toUpperCase()
  const usdToEurRate = getUsdToEurRate(options.usdToEurRate)
  const move = trade.tradeType === 'Sell' ? entry - target : target - entry
  const rewardInProfitCurrency = move * lot * contractSize

  return convertCurrency(rewardInProfitCurrency, profitCurrency, targetCurrency, usdToEurRate)
}

export function calculateTradeRewardTp1(trade, options = {}) {
  return calculateTradeRewardForTarget(trade, 'tp1', options)
}

export function calculateTradeRiskReward(trade, profile = null) {
  const currency = getPreferredCurrency(profile)
  const usdToEurRate = getProfileUsdToEurRate(profile)
  const risk = calculateTradeRisk(trade, profile?.accountBalance, { currency, usdToEurRate })

  if (!risk) return null

  const rewards = ['tp1', 'tp2', 'tp3', 'tp4'].map((key, index) => {
    const amount = calculateTradeRewardForTarget(trade, key, { currency, usdToEurRate })
    const ratio = amount !== null && risk.riskAmount > 0 ? amount / risk.riskAmount : null

    return {
      key,
      label: `TP${index + 1}`,
      amount,
      ratio,
    }
  })

  const validRatios = rewards
    .map((reward) => reward.ratio)
    .filter((ratio) => Number.isFinite(ratio))

  return {
    ...risk,
    rewards,
    averageRiskReward:
      validRatios.length > 0
        ? validRatios.reduce((sum, ratio) => sum + ratio, 0) / validRatios.length
        : null,
  }
}

export function buildSetupTagStats(trades) {
  const map = {}

  for (const trade of trades) {
    const tag = trade.setupTag || null
    if (!tag) continue

    if (!map[tag]) map[tag] = { tag, count: 0, wins: 0, totalPnl: 0 }

    map[tag].count += 1
    if (Number(trade.profitLoss || 0) > 0) map[tag].wins += 1
    map[tag].totalPnl += Number(trade.profitLoss || 0)
  }

  return Object.values(map)
    .map((s) => ({
      ...s,
      winRate: s.count > 0 ? Math.round((s.wins / s.count) * 100) : 0,
      avgPnl: s.count > 0 ? s.totalPnl / s.count : 0,
    }))
    .sort((a, b) => b.count - a.count)
}

const DOW_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export function buildDayOfWeekStats(trades) {
  const map = {}

  for (let i = 0; i < 7; i++) {
    map[i] = { dow: i, label: DOW_LABELS[i], count: 0, wins: 0, totalPnl: 0 }
  }

  for (const trade of trades) {
    if (!trade.date) continue
    const dow = (new Date(`${trade.date}T00:00:00`).getDay() + 6) % 7
    map[dow].count += 1
    if (Number(trade.profitLoss || 0) > 0) map[dow].wins += 1
    map[dow].totalPnl += Number(trade.profitLoss || 0)
  }

  return Object.values(map)
    .map((d) => ({
      ...d,
      winRate: d.count > 0 ? Math.round((d.wins / d.count) * 100) : 0,
      avgPnl: d.count > 0 ? d.totalPnl / d.count : 0,
    }))
    .sort((a, b) => a.dow - b.dow)
}

export function buildEquityCurve(trades) {
  const sorted = [...trades]
    .filter((t) => t.date)
    .sort((a, b) => a.date.localeCompare(b.date))

  let cumulative = 0
  return sorted.map((trade) => {
    cumulative += Number(trade.profitLoss || 0)
    return { date: trade.date, value: cumulative }
  })
}

export function buildDrawdown(trades) {
  const curve = buildEquityCurve(trades)
  if (curve.length === 0) {
    return { currentDrawdown: 0, maxDrawdown: 0, equityPeak: 0, lowestEquityAfterPeak: 0 }
  }

  let peak = -Infinity
  let maxDrawdown = 0
  let equityPeak = 0
  let lowestEquityAfterPeak = 0
  let runningTrough = 0

  for (const point of curve) {
    if (point.value > peak) {
      peak = point.value
      equityPeak = point.value
      runningTrough = point.value
    }

    if (point.value < runningTrough) runningTrough = point.value

    const dd = peak - point.value
    if (dd > maxDrawdown) {
      maxDrawdown = dd
      lowestEquityAfterPeak = point.value
    }
  }

  const currentEquity = curve[curve.length - 1].value
  const currentDrawdown = Math.max(0, peak - currentEquity)

  return { currentDrawdown, maxDrawdown, equityPeak, lowestEquityAfterPeak }
}

function goalStatus(value, limit, mode = 'limit') {
  const target = Number(limit)
  if (!target || target <= 0) return 'missing'

  const current = Number(value || 0)

  if (mode === 'target') {
    if (current >= target) return 'safe'
    if (current >= target * 0.7) return 'warning'
    return 'danger'
  }

  if (current > target) return 'danger'
  if (current >= target * 0.8) return 'warning'
  return 'safe'
}

export function buildTradeGoals(trades, profile) {
  const today = new Date().toISOString().slice(0, 10)
  const todaysTrades = trades.filter((trade) => trade.date === today)
  const currency = getPreferredCurrency(profile)
  const usdToEurRate = getProfileUsdToEurRate(profile)

  const riskUsedToday = todaysTrades.reduce((sum, trade) => {
    const risk = calculateTradeRisk(trade, profile?.accountBalance, { currency, usdToEurRate })
    return sum + Number(risk?.riskAmount || 0)
  }, 0)

  const profitLossToday = todaysTrades.reduce(
    (sum, trade) => sum + Number(trade.profitLoss || 0),
    0
  )

  return {
    tradesToday: todaysTrades.length,
    maxTradesPerDay: Number(profile?.maxTradesPerDay) || null,
    tradesStatus: goalStatus(todaysTrades.length, profile?.maxTradesPerDay),
    riskUsedToday,
    maxRiskPerDay: Number(profile?.maxRiskPerDay) || null,
    riskStatus: goalStatus(riskUsedToday, profile?.maxRiskPerDay),
    profitLossToday,
    dailyProfitTarget: Number(profile?.dailyProfitTarget) || null,
    profitStatus: goalStatus(profitLossToday, profile?.dailyProfitTarget, 'target'),
  }
}

export function buildDisciplineStats(trades) {
  const rated = trades.filter((t) => t.satisfactionEmoji)
  const total = rated.length

  if (total === 0) return { total: 0, good: 0, neutral: 0, bad: 0, goodPct: 0, neutralPct: 0, badPct: 0 }

  const good = rated.filter((t) => t.satisfactionEmoji === '😄' || t.satisfactionEmoji === '🙂').length
  const neutral = rated.filter((t) => t.satisfactionEmoji === '😐').length
  const bad = rated.filter((t) => t.satisfactionEmoji === '😞' || t.satisfactionEmoji === '😡').length

  return {
    total,
    good,
    neutral,
    bad,
    goodPct: Math.round((good / total) * 100),
    neutralPct: Math.round((neutral / total) * 100),
    badPct: Math.round((bad / total) * 100),
  }
}

export function calculateTradeR(trade, profile) {
  if (normalizeTradeStatus(trade.status) === 'open') return null
  const currency = getPreferredCurrency(profile)
  const usdToEurRate = getProfileUsdToEurRate(profile)
  const riskInfo = calculateTradeRisk(trade, profile?.accountBalance, { currency, usdToEurRate })
  if (!riskInfo || !Number.isFinite(riskInfo.riskAmount) || riskInfo.riskAmount <= 0) return null
  const pnlEur = Number(trade.profitLossEur ?? trade.profitLoss ?? 0)
  const pnlInCurrency = convertFromEur(pnlEur, currency, usdToEurRate)
  return pnlInCurrency / riskInfo.riskAmount
}

export function buildRMultipleStats(trades, profile) {
  const rs = trades
    .map((trade) => calculateTradeR(trade, profile))
    .filter((r) => r !== null && Number.isFinite(r))
  if (rs.length === 0) return { count: 0, avgR: null, bestR: null, worstR: null }
  return {
    count: rs.length,
    avgR: rs.reduce((sum, r) => sum + r, 0) / rs.length,
    bestR: Math.max(...rs),
    worstR: Math.min(...rs),
  }
}

export function buildStreaks(trades) {
  const closed = [...trades]
    .filter((t) => normalizeTradeStatus(t.status) !== 'open')
    .sort((a, b) => {
      const d = String(a.date || '').localeCompare(String(b.date || ''))
      return d !== 0 ? d : String(a.createdAt || '').localeCompare(String(b.createdAt || ''))
    })

  if (closed.length === 0) {
    return { currentWinStreak: 0, currentLossStreak: 0, longestWinStreak: 0, longestLossStreak: 0 }
  }

  let longestWin = 0
  let longestLoss = 0
  let currentWin = 0
  let currentLoss = 0

  for (const trade of closed) {
    const pnl = Number(trade.profitLoss || 0)
    if (pnl > 0) {
      currentWin++
      currentLoss = 0
      if (currentWin > longestWin) longestWin = currentWin
    } else if (pnl < 0) {
      currentLoss++
      currentWin = 0
      if (currentLoss > longestLoss) longestLoss = currentLoss
    } else {
      currentWin = 0
      currentLoss = 0
    }
  }

  return {
    currentWinStreak: currentWin,
    currentLossStreak: currentLoss,
    longestWinStreak: longestWin,
    longestLossStreak: longestLoss,
  }
}

function classifyTradingSession(createdAt) {
  if (!createdAt) return null
  const hour = new Date(createdAt).getUTCHours()
  if (hour < 8) return 'Asia'
  if (hour < 13) return 'London'
  if (hour < 21) return 'New York'
  return null
}

export function buildSessionStats(trades) {
  const sessions = ['Asia', 'London', 'New York']
  const map = Object.fromEntries(
    sessions.map((s) => [s, { session: s, count: 0, wins: 0, totalPnl: 0 }])
  )

  for (const trade of trades) {
    const session = classifyTradingSession(trade.createdAt)
    if (!session) continue
    map[session].count++
    if (Number(trade.profitLoss || 0) > 0) map[session].wins++
    map[session].totalPnl += Number(trade.profitLoss || 0)
  }

  return sessions
    .filter((s) => map[s].count > 0)
    .map((s) => ({
      ...map[s],
      winRate: Math.round((map[s].wins / map[s].count) * 100),
      avgPnl: map[s].totalPnl / map[s].count,
    }))
}

export function buildMonthlyStats(trades) {
  const map = {}

  for (const trade of trades) {
    if (!trade.date) continue
    const month = trade.date.slice(0, 7)
    if (!map[month]) map[month] = { month, count: 0, wins: 0, totalPnl: 0, tradeList: [] }
    const pnl = Number(trade.profitLoss || 0)
    map[month].count++
    if (pnl > 0) map[month].wins++
    map[month].totalPnl += pnl
    map[month].tradeList.push(trade)
  }

  return Object.values(map)
    .map((m) => {
      const pnlValues = m.tradeList.map((t) => Number(t.profitLoss || 0))
      const dd = buildDrawdown(m.tradeList)
      return {
        month: m.month,
        count: m.count,
        wins: m.wins,
        totalPnl: m.totalPnl,
        winRate: Math.round((m.wins / m.count) * 100),
        bestPnl: pnlValues.length > 0 ? Math.max(...pnlValues) : 0,
        worstPnl: pnlValues.length > 0 ? Math.min(...pnlValues) : 0,
        maxDrawdown: dd.maxDrawdown,
      }
    })
    .sort((a, b) => b.month.localeCompare(a.month))
}

export function buildTradeMarkerStats(trades) {
  const favorites = trades.filter((trade) => trade.isFavorite)
  const mistakes = trades.filter((trade) => trade.isMistake)

  return {
    favoriteCount: favorites.length,
    mistakeCount: mistakes.length,
    favoritePnl: favorites.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0),
    mistakePnl: mistakes.reduce((sum, trade) => sum + Number(trade.profitLoss || 0), 0),
  }
}

export function buildFtmoStatus(trades, profile) {
  const dailyLimit = Number(profile?.dailyLossLimit)
  const maxLimit = Number(profile?.maxLossLimit)

  if (!dailyLimit || !maxLimit) return null

  const today = new Date().toISOString().slice(0, 10)

  const todayPnl = trades
    .filter((t) => t.date === today)
    .reduce((sum, t) => sum + Number(t.profitLoss || 0), 0)

  const totalPnl = trades.reduce((sum, t) => sum + Number(t.profitLoss || 0), 0)

  const dailyLossUsed = Math.max(0, -todayPnl)
  const maxLossUsed = Math.max(0, -totalPnl)

  const dailyRemaining = dailyLimit - dailyLossUsed
  const maxRemaining = maxLimit - maxLossUsed

  const dailyPct = dailyLimit > 0 ? (dailyRemaining / dailyLimit) * 100 : 100
  const maxPct = maxLimit > 0 ? (maxRemaining / maxLimit) * 100 : 100

  function getStatus(pct) {
    if (pct <= 0) return 'breached'
    if (pct <= 25) return 'danger'
    if (pct <= 50) return 'warning'
    return 'safe'
  }

  return {
    dailyLossUsed,
    dailyRemaining,
    dailyLimit,
    dailyPct,
    dailyStatus: getStatus(dailyPct),
    maxLossUsed,
    maxRemaining,
    maxLimit,
    maxPct,
    maxStatus: getStatus(maxPct),
  }
}

export function tradesToCSV(trades) {
  const headers = [
    'Date',
    'Symbol',
    'Type',
    'Entry Price',
    'Current Price',
    'Lot Size',
    'Entry Zone From',
    'Entry Zone To',
    'Stop Loss',
    'TP1',
    'TP2',
    'TP3',
    'TP4',
    'Status',
    'Feeling',
    'Reason For Entry',
    'Satisfaction',
    'Satisfaction Reason',
    'Profit/Loss (EUR)',
  ]

  const rows = trades.map((trade) => [
    trade.date,
    trade.symbol,
    trade.tradeType,
    trade.entryPrice,
    trade.currentPrice ?? '',
    trade.lotSize,
    trade.entryZoneFrom ?? '',
    trade.entryZoneTo ?? '',
    trade.stopLoss ?? '',
    trade.tp1 ?? '',
    trade.tp2 ?? '',
    trade.tp3 ?? '',
    trade.tp4 ?? '',
    normalizeTradeStatus(trade.status),
    trade.feeling ?? '',
    trade.reasonForEntry ?? '',
    trade.satisfactionEmoji ?? '',
    trade.satisfactionReason ?? '',
    Number(trade.profitLoss || 0).toFixed(2),
  ])

  const escapeCsvValue = (value) => `"${String(value).replaceAll('"', '""')}"`

  return [headers, ...rows].map((row) => row.map(escapeCsvValue).join(',')).join('\n')
}
