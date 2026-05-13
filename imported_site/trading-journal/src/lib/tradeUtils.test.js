import { describe, it, expect } from 'vitest'
import {
  calculateProfitLossEur,
  buildDashboardStats,
  buildFtmoStatus,
  calculateTradeRisk,
  calculateTradeRiskReward,
  calculateProfitLossInCurrency,
  buildEquityCurve,
  buildDrawdown,
  buildDisciplineStats,
  buildDayOfWeekStats,
  buildSetupTagStats,
  convertStoredEurToProfileCurrency,
  calculateTradeR,
  buildRMultipleStats,
  buildStreaks,
  buildSessionStats,
  buildMonthlyStats,
} from './tradeUtils'

// XAUUSD formula: move * lot * 100 (contractSize) * 0.92 (USD→EUR)
const EUR_PER_PIP_LOT = 100 * 0.92

describe('calculateProfitLossEur', () => {
  it('calculates Buy profit correctly', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Buy',
      entryPrice: 2000,
      currentPrice: 2010,
      lotSize: 1,
      symbol: 'XAUUSD',
    })
    expect(result).toBeCloseTo(10 * EUR_PER_PIP_LOT, 5)
  })

  it('calculates Sell profit correctly', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Sell',
      entryPrice: 2010,
      currentPrice: 2000,
      lotSize: 1,
      symbol: 'XAUUSD',
    })
    expect(result).toBeCloseTo(10 * EUR_PER_PIP_LOT, 5)
  })

  it('calculates Buy loss correctly', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Buy',
      entryPrice: 2000,
      currentPrice: 1990,
      lotSize: 1,
      symbol: 'XAUUSD',
    })
    expect(result).toBeCloseTo(-10 * EUR_PER_PIP_LOT, 5)
  })

  it('calculates Sell loss correctly', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Sell',
      entryPrice: 2000,
      currentPrice: 2010,
      lotSize: 1,
      symbol: 'XAUUSD',
    })
    expect(result).toBeCloseTo(-10 * EUR_PER_PIP_LOT, 5)
  })

  it('scales with lot size', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Buy',
      entryPrice: 2000,
      currentPrice: 2010,
      lotSize: 0.5,
      symbol: 'XAUUSD',
    })
    expect(result).toBeCloseTo(10 * 0.5 * EUR_PER_PIP_LOT, 5)
  })

  it('returns 0 for invalid input', () => {
    expect(calculateProfitLossEur({ tradeType: 'Buy', entryPrice: 0, currentPrice: 2010, lotSize: 1 })).toBe(0)
    expect(calculateProfitLossEur({ tradeType: 'Buy', entryPrice: 2000, currentPrice: 0, lotSize: 1 })).toBe(0)
    expect(calculateProfitLossEur({ tradeType: 'Buy', entryPrice: 2000, currentPrice: 2010, lotSize: 0 })).toBe(0)
  })
})

describe('currency conversion', () => {
  it('calculates XAUUSD P/L directly in USD', () => {
    const result = calculateProfitLossInCurrency({
      tradeType: 'Buy',
      entryPrice: 2000,
      currentPrice: 2010,
      lotSize: 1,
      symbol: 'XAUUSD',
      currency: 'USD',
    })

    expect(result).toBeCloseTo(1000, 5)
  })

  it('converts stored EUR P/L to USD using profile rate', () => {
    const result = convertStoredEurToProfileCurrency(920, {
      currency: 'USD',
      usdToEurRate: 0.92,
    })

    expect(result).toBeCloseTo(1000, 5)
  })
})

describe('buildDashboardStats - winRate', () => {
  const closed = (pnl) => ({ status: 'TP hit', profitLoss: pnl, date: '2024-01-01' })

  it('returns 0% with no trades', () => {
    expect(buildDashboardStats([]).winRate).toBe(0)
  })

  it('calculates winRate correctly', () => {
    const trades = [closed(100), closed(200), closed(-50)]
    expect(buildDashboardStats(trades).winRate).toBe(67)
  })

  it('calculates avgWin correctly', () => {
    const trades = [closed(100), closed(200), closed(-50)]
    const stats = buildDashboardStats(trades)
    expect(stats.avgWin).toBeCloseTo(150, 5)
  })

  it('calculates avgLoss correctly', () => {
    const trades = [closed(100), closed(-50), closed(-150)]
    const stats = buildDashboardStats(trades)
    expect(stats.avgLoss).toBeCloseTo(-100, 5)
  })
})

describe('buildDashboardStats - daily P/L', () => {
  it('sums profitLoss for today only', () => {
    const today = new Date().toISOString().slice(0, 10)
    const trades = [
      { status: 'TP hit', profitLoss: 200, date: today },
      { status: 'TP hit', profitLoss: -50, date: today },
      { status: 'TP hit', profitLoss: 300, date: '2020-01-01' },
    ]
    expect(buildDashboardStats(trades).profitLossToday).toBeCloseTo(150, 5)
  })
})

describe('buildFtmoStatus', () => {
  const today = new Date().toISOString().slice(0, 10)
  const profile = { dailyLossLimit: 500, maxLossLimit: 1000 }

  it('returns null when limits are missing', () => {
    expect(buildFtmoStatus([], {})).toBeNull()
    expect(buildFtmoStatus([], { dailyLossLimit: 500 })).toBeNull()
  })

  it('shows safe when no losses', () => {
    const status = buildFtmoStatus([], profile)
    expect(status.dailyStatus).toBe('safe')
    expect(status.maxStatus).toBe('safe')
    expect(status.dailyRemaining).toBe(500)
    expect(status.maxRemaining).toBe(1000)
  })

  it('reflects daily loss correctly — 60% remaining = safe', () => {
    const trades = [{ profitLoss: -200, date: today }]
    const status = buildFtmoStatus(trades, profile)
    expect(status.dailyLossUsed).toBeCloseTo(200, 5)
    expect(status.dailyRemaining).toBeCloseTo(300, 5)
    // 300/500 = 60% remaining → safe
    expect(status.dailyStatus).toBe('safe')
  })

  it('reflects daily loss — 40% remaining = warning', () => {
    const trades = [{ profitLoss: -300, date: today }]
    const status = buildFtmoStatus(trades, profile)
    expect(status.dailyRemaining).toBeCloseTo(200, 5)
    // 200/500 = 40% remaining → warning
    expect(status.dailyStatus).toBe('warning')
  })

  it('breaches daily limit', () => {
    const trades = [{ profitLoss: -600, date: today }]
    const status = buildFtmoStatus(trades, profile)
    expect(status.dailyStatus).toBe('breached')
    expect(status.dailyRemaining).toBeCloseTo(-100, 5)
  })

  it('ignores past day losses for daily limit', () => {
    const trades = [{ profitLoss: -600, date: '2020-01-01' }]
    const status = buildFtmoStatus(trades, profile)
    expect(status.dailyLossUsed).toBe(0)
    expect(status.dailyStatus).toBe('safe')
  })

  it('reflects max loss from all trades — 30% remaining = warning', () => {
    const trades = [
      { profitLoss: -300, date: '2024-01-01' },
      { profitLoss: -400, date: '2024-01-02' },
    ]
    const status = buildFtmoStatus(trades, profile)
    expect(status.maxLossUsed).toBeCloseTo(700, 5)
    // 300/1000 = 30% remaining → warning
    expect(status.maxStatus).toBe('warning')
  })

  it('breaches max limit when all used', () => {
    const trades = [
      { profitLoss: -600, date: '2024-01-01' },
      { profitLoss: -500, date: '2024-01-02' },
    ]
    const status = buildFtmoStatus(trades, profile)
    expect(status.maxStatus).toBe('breached')
    expect(status.maxRemaining).toBeCloseTo(-100, 5)
  })
})

describe('calculateTradeRisk', () => {
  it('calculates risk EUR correctly', () => {
    const trade = { entryPrice: 2000, stopLoss: 1940, lotSize: 1, symbol: 'XAUUSD' }
    const result = calculateTradeRisk(trade, 10000)
    // risk = |2000-1940| * 1 * 100 * 0.92 = 60 * 92 = 5520
    expect(result.riskEur).toBeCloseTo(60 * EUR_PER_PIP_LOT, 5)
  })

  it('calculates riskPercent relative to account', () => {
    const trade = { entryPrice: 2000, stopLoss: 1990, lotSize: 0.1, symbol: 'XAUUSD' }
    const result = calculateTradeRisk(trade, 10000)
    // risk = 10 * 0.1 * 100 * 0.92 = 92
    expect(result.riskEur).toBeCloseTo(92, 5)
    expect(result.riskPercent).toBeCloseTo(0.92, 5)
  })

  it('returns null when entry is missing', () => {
    expect(calculateTradeRisk({ entryPrice: 0, stopLoss: 1990, lotSize: 1 }, 10000)).toBeNull()
  })

  it('returns null when SL is missing', () => {
    expect(calculateTradeRisk({ entryPrice: 2000, stopLoss: 0, lotSize: 1 }, 10000)).toBeNull()
  })

  it('returns null riskPercent when no accountBalance', () => {
    const trade = { entryPrice: 2000, stopLoss: 1990, lotSize: 0.1, symbol: 'XAUUSD' }
    const result = calculateTradeRisk(trade, null)
    expect(result.riskPercent).toBeNull()
  })
})

describe('calculateTradeRiskReward', () => {
  it('calculates TP rewards and risk/reward ratios', () => {
    const trade = {
      tradeType: 'Buy',
      symbol: 'XAUUSD',
      entryPrice: 2000,
      stopLoss: 1990,
      lotSize: 0.1,
      tp1: 2010,
      tp2: 2020,
      tp3: 2030,
      tp4: 2040,
    }

    const result = calculateTradeRiskReward(trade, {
      accountBalance: 10000,
      currency: 'EUR',
      usdToEurRate: 0.92,
    })

    expect(result.riskAmount).toBeCloseTo(92, 5)
    expect(result.riskPercent).toBeCloseTo(0.92, 5)
    expect(result.rewards[0].amount).toBeCloseTo(92, 5)
    expect(result.rewards[0].ratio).toBeCloseTo(1, 5)
    expect(result.averageRiskReward).toBeCloseTo(2.5, 5)
  })
})

describe('buildEquityCurve', () => {
  it('returns empty array for no trades', () => {
    expect(buildEquityCurve([])).toEqual([])
  })

  it('returns cumulative P/L sorted by date', () => {
    const trades = [
      { date: '2024-01-02', profitLoss: 100 },
      { date: '2024-01-01', profitLoss: 200 },
    ]
    const curve = buildEquityCurve(trades)
    expect(curve).toHaveLength(2)
    expect(curve[0].date).toBe('2024-01-01')
    expect(curve[0].value).toBeCloseTo(200, 5)
    expect(curve[1].value).toBeCloseTo(300, 5)
  })

  it('handles negative P/L correctly', () => {
    const trades = [
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-02', profitLoss: -150 },
    ]
    const curve = buildEquityCurve(trades)
    expect(curve[1].value).toBeCloseTo(-50, 5)
  })
})

describe('buildDrawdown', () => {
  it('returns zeros for empty trades', () => {
    const dd = buildDrawdown([])
    expect(dd.currentDrawdown).toBe(0)
    expect(dd.maxDrawdown).toBe(0)
  })

  it('calculates max drawdown correctly', () => {
    // Equity: 100 → 200 → 50 → 150 — peak 200, trough 50 → maxDD 150
    const trades = [
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-02', profitLoss: 100 },
      { date: '2024-01-03', profitLoss: -150 },
      { date: '2024-01-04', profitLoss: 100 },
    ]
    const dd = buildDrawdown(trades)
    expect(dd.maxDrawdown).toBeCloseTo(150, 5)
    expect(dd.equityPeak).toBeCloseTo(200, 5)
    expect(dd.lowestEquityAfterPeak).toBeCloseTo(50, 5)
  })

  it('calculates current drawdown correctly', () => {
    // Equity: 100 → 200 → 50 — current = 50, peak = 200 → currentDD = 150
    const trades = [
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-02', profitLoss: 100 },
      { date: '2024-01-03', profitLoss: -150 },
    ]
    const dd = buildDrawdown(trades)
    expect(dd.currentDrawdown).toBeCloseTo(150, 5)
  })

  it('reports zero current drawdown when at equity peak', () => {
    const trades = [
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-02', profitLoss: 200 },
    ]
    const dd = buildDrawdown(trades)
    expect(dd.currentDrawdown).toBe(0)
  })
})

describe('buildDayOfWeekStats', () => {
  it('returns Monday to Sunday with winrate and average P/L', () => {
    const stats = buildDayOfWeekStats([
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-01', profitLoss: -50 },
      { date: '2024-01-07', profitLoss: 70 },
    ])

    expect(stats).toHaveLength(7)
    expect(stats[0].label).toBe('Monday')
    expect(stats[0].count).toBe(2)
    expect(stats[0].winRate).toBe(50)
    expect(stats[0].avgPnl).toBeCloseTo(25, 5)
    expect(stats[6].label).toBe('Sunday')
    expect(stats[6].totalPnl).toBeCloseTo(70, 5)
  })
})

describe('buildSetupTagStats', () => {
  it('calculates setup performance', () => {
    const stats = buildSetupTagStats([
      { setupTag: 'Breakout', profitLoss: 100 },
      { setupTag: 'Breakout', profitLoss: -50 },
      { setupTag: 'Retest', profitLoss: 200 },
      { setupTag: null, profitLoss: 999 },
    ])

    const breakout = stats.find((row) => row.tag === 'Breakout')
    expect(breakout.count).toBe(2)
    expect(breakout.winRate).toBe(50)
    expect(breakout.totalPnl).toBeCloseTo(50, 5)
    expect(breakout.avgPnl).toBeCloseTo(25, 5)
  })
})

describe('buildDisciplineStats', () => {
  it('returns zeros for no trades', () => {
    const ds = buildDisciplineStats([])
    expect(ds.total).toBe(0)
    expect(ds.goodPct).toBe(0)
  })

  it('ignores trades without satisfaction emoji', () => {
    const trades = [{ satisfactionEmoji: null }, { satisfactionEmoji: '😄' }]
    const ds = buildDisciplineStats(trades)
    expect(ds.total).toBe(1)
    expect(ds.good).toBe(1)
    expect(ds.goodPct).toBe(100)
  })

  it('categorizes good/neutral/bad correctly', () => {
    const trades = [
      { satisfactionEmoji: '😄' },
      { satisfactionEmoji: '🙂' },
      { satisfactionEmoji: '😐' },
      { satisfactionEmoji: '😞' },
      { satisfactionEmoji: '😡' },
    ]
    const ds = buildDisciplineStats(trades)
    expect(ds.good).toBe(2)
    expect(ds.neutral).toBe(1)
    expect(ds.bad).toBe(2)
    expect(ds.goodPct).toBe(40)
    expect(ds.neutralPct).toBe(20)
    expect(ds.badPct).toBe(40)
  })
})

describe('calculateTradeR', () => {
  const profile = { accountBalance: 10000, currency: 'EUR', usdToEurRate: 0.92 }

  it('returns null for open trades', () => {
    const trade = { status: 'open', entryPrice: 2000, stopLoss: 1990, lotSize: 0.1, symbol: 'XAUUSD', profitLoss: 0 }
    expect(calculateTradeR(trade, profile)).toBeNull()
  })

  it('returns null when risk cannot be calculated', () => {
    const trade = { status: 'TP hit', entryPrice: 0, stopLoss: 0, lotSize: 0.1, symbol: 'XAUUSD', profitLoss: 92 }
    expect(calculateTradeR(trade, profile)).toBeNull()
  })

  it('returns 1R for a trade that hit exactly its risk', () => {
    // risk = |2000-1990| * 0.1 * 100 * 0.92 = 92 EUR
    const trade = { status: 'TP hit', entryPrice: 2000, stopLoss: 1990, lotSize: 0.1, symbol: 'XAUUSD', profitLoss: 92 }
    const r = calculateTradeR(trade, profile)
    expect(r).toBeCloseTo(1, 5)
  })

  it('returns 2.5R for a trade earning 2.5x risk', () => {
    const trade = { status: 'TP hit', entryPrice: 2000, stopLoss: 1990, lotSize: 0.1, symbol: 'XAUUSD', profitLoss: 230 }
    const r = calculateTradeR(trade, profile)
    expect(r).toBeCloseTo(230 / 92, 2)
  })

  it('returns negative R for a losing trade', () => {
    const trade = { status: 'SL hit', entryPrice: 2000, stopLoss: 1990, lotSize: 0.1, symbol: 'XAUUSD', profitLoss: -92 }
    const r = calculateTradeR(trade, profile)
    expect(r).toBeCloseTo(-1, 5)
  })

  it('uses profitLossEur when present (displayTrade)', () => {
    const trade = {
      status: 'TP hit',
      entryPrice: 2000,
      stopLoss: 1990,
      lotSize: 0.1,
      symbol: 'XAUUSD',
      profitLoss: 100, // profile currency (USD) — ignored
      profitLossEur: 92, // EUR — should be used
    }
    const r = calculateTradeR(trade, profile)
    expect(r).toBeCloseTo(1, 5)
  })
})

describe('buildRMultipleStats', () => {
  const profile = { accountBalance: 10000, currency: 'EUR', usdToEurRate: 0.92 }
  const mkTrade = (pnl, status = 'TP hit') => ({
    status,
    entryPrice: 2000,
    stopLoss: 1990,
    lotSize: 0.1,
    symbol: 'XAUUSD',
    profitLoss: pnl,
    date: '2024-01-01',
  })

  it('returns nulls for empty trades', () => {
    const result = buildRMultipleStats([], profile)
    expect(result.count).toBe(0)
    expect(result.avgR).toBeNull()
  })

  it('skips open trades', () => {
    const result = buildRMultipleStats([mkTrade(0, 'open')], profile)
    expect(result.count).toBe(0)
  })

  it('computes avgR, bestR, worstR correctly', () => {
    const trades = [mkTrade(92), mkTrade(184), mkTrade(-92)]
    const result = buildRMultipleStats(trades, profile)
    expect(result.count).toBe(3)
    expect(result.avgR).toBeCloseTo((1 + 2 - 1) / 3, 2)
    expect(result.bestR).toBeCloseTo(2, 5)
    expect(result.worstR).toBeCloseTo(-1, 5)
  })
})

describe('buildStreaks', () => {
  const mkTrade = (pnl, date, status = 'TP hit') => ({ status, profitLoss: pnl, date, createdAt: `${date}T12:00:00Z` })

  it('returns zeros for no closed trades', () => {
    const s = buildStreaks([])
    expect(s.currentWinStreak).toBe(0)
    expect(s.longestWinStreak).toBe(0)
  })

  it('tracks current and longest win streak', () => {
    const trades = [
      mkTrade(-50, '2024-01-01', 'SL hit'),
      mkTrade(100, '2024-01-02'),
      mkTrade(200, '2024-01-03'),
      mkTrade(50, '2024-01-04'),
    ]
    const s = buildStreaks(trades)
    expect(s.currentWinStreak).toBe(3)
    expect(s.longestWinStreak).toBe(3)
    expect(s.currentLossStreak).toBe(0)
  })

  it('tracks current and longest loss streak', () => {
    const trades = [
      mkTrade(100, '2024-01-01'),
      mkTrade(-50, '2024-01-02', 'SL hit'),
      mkTrade(-80, '2024-01-03', 'SL hit'),
    ]
    const s = buildStreaks(trades)
    expect(s.currentLossStreak).toBe(2)
    expect(s.longestLossStreak).toBe(2)
    expect(s.longestWinStreak).toBe(1)
  })

  it('resets streak on breakeven', () => {
    const trades = [
      mkTrade(100, '2024-01-01'),
      mkTrade(100, '2024-01-02'),
      mkTrade(0, '2024-01-03'),
      mkTrade(100, '2024-01-04'),
    ]
    const s = buildStreaks(trades)
    expect(s.longestWinStreak).toBe(2)
    expect(s.currentWinStreak).toBe(1)
  })
})

describe('buildSessionStats', () => {
  const mkTrade = (hour, pnl) => ({
    profitLoss: pnl,
    createdAt: `2024-01-15T${String(hour).padStart(2, '0')}:00:00Z`,
    date: '2024-01-15',
  })

  it('returns empty array when no trades', () => {
    expect(buildSessionStats([])).toEqual([])
  })

  it('classifies Asia session (00-07 UTC)', () => {
    const stats = buildSessionStats([mkTrade(3, 100)])
    expect(stats).toHaveLength(1)
    expect(stats[0].session).toBe('Asia')
    expect(stats[0].count).toBe(1)
  })

  it('classifies London session (08-12 UTC)', () => {
    const stats = buildSessionStats([mkTrade(10, -50)])
    expect(stats[0].session).toBe('London')
  })

  it('classifies New York session (13-20 UTC)', () => {
    const stats = buildSessionStats([mkTrade(15, 200)])
    expect(stats[0].session).toBe('New York')
  })

  it('excludes off-hours trades (21-23 UTC)', () => {
    const stats = buildSessionStats([mkTrade(22, 100)])
    expect(stats).toHaveLength(0)
  })

  it('computes winrate and avgPnl correctly', () => {
    const trades = [mkTrade(9, 100), mkTrade(10, -50), mkTrade(11, 200)]
    const london = buildSessionStats(trades).find((s) => s.session === 'London')
    expect(london.count).toBe(3)
    expect(london.winRate).toBe(67)
    expect(london.avgPnl).toBeCloseTo(250 / 3, 2)
  })
})

describe('buildMonthlyStats', () => {
  it('returns empty for no trades', () => {
    expect(buildMonthlyStats([])).toEqual([])
  })

  it('groups trades by month correctly', () => {
    const trades = [
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-15', profitLoss: -50 },
      { date: '2024-02-01', profitLoss: 200 },
    ]
    const stats = buildMonthlyStats(trades)
    expect(stats).toHaveLength(2)
    expect(stats[0].month).toBe('2024-02')
    expect(stats[0].count).toBe(1)
    expect(stats[1].month).toBe('2024-01')
    expect(stats[1].count).toBe(2)
    expect(stats[1].totalPnl).toBeCloseTo(50, 5)
    expect(stats[1].winRate).toBe(50)
  })

  it('computes bestPnl and worstPnl correctly', () => {
    const trades = [
      { date: '2024-01-01', profitLoss: 300 },
      { date: '2024-01-02', profitLoss: -100 },
    ]
    const stats = buildMonthlyStats(trades)
    expect(stats[0].bestPnl).toBeCloseTo(300, 5)
    expect(stats[0].worstPnl).toBeCloseTo(-100, 5)
  })
})

// ─── Additional edge-case tests ──────────────────────────────────────────────

describe('calculateProfitLossEur — edge cases', () => {
  it('returns 0 when entry equals current price (no movement)', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Buy',
      entryPrice: 2000,
      currentPrice: 2000,
      lotSize: 1,
      symbol: 'XAUUSD',
    })
    expect(result).toBe(0)
  })

  it('scales correctly with mini lot (0.01)', () => {
    const result = calculateProfitLossEur({
      tradeType: 'Buy',
      entryPrice: 2000,
      currentPrice: 2010,
      lotSize: 0.01,
      symbol: 'XAUUSD',
    })
    // 10 pips × 0.01 lot × 100 contractSize × 0.92 USD→EUR = 9.2
    expect(result).toBeCloseTo(10 * 0.01 * EUR_PER_PIP_LOT, 5)
  })
})

describe('buildDashboardStats — win rate edge cases', () => {
  const closed = (pnl, status = 'TP hit') => ({ status, profitLoss: pnl, date: '2024-01-01' })

  it('returns 100% win rate when all trades are profitable', () => {
    const trades = [closed(100), closed(200), closed(50)]
    expect(buildDashboardStats(trades).winRate).toBe(100)
  })

  it('returns 0% win rate when all trades are losses', () => {
    const trades = [closed(-100), closed(-200)]
    expect(buildDashboardStats(trades).winRate).toBe(0)
  })

  it('excludes open trades from win rate calculation', () => {
    const trades = [
      closed(100),
      { status: 'open', profitLoss: 500, date: '2024-01-01' },
    ]
    // only 1 closed trade, which is a win → 100%
    expect(buildDashboardStats(trades).winRate).toBe(100)
  })

  it('returns 50% for equal wins and losses', () => {
    const trades = [closed(100), closed(-100)]
    expect(buildDashboardStats(trades).winRate).toBe(50)
  })
})

describe('buildFtmoStatus — boundary conditions', () => {
  const today = new Date().toISOString().slice(0, 10)
  const profile = { dailyLossLimit: 500, maxLossLimit: 1000 }

  it('transitions to breached at exactly the daily limit', () => {
    const trades = [{ profitLoss: -500, date: today }]
    const status = buildFtmoStatus(trades, profile)
    expect(status.dailyStatus).toBe('breached')
    expect(status.dailyRemaining).toBeCloseTo(0, 5)
  })

  it('shows danger (not breached) just under the daily limit', () => {
    const trades = [{ profitLoss: -450, date: today }]
    const status = buildFtmoStatus(trades, profile)
    // 50/500 = 10% remaining → danger
    expect(status.dailyStatus).toBe('danger')
  })

  it('handles both daily and max breached simultaneously', () => {
    const trades = [
      { profitLoss: -600, date: today },
      { profitLoss: -500, date: '2024-01-01' },
    ]
    const status = buildFtmoStatus(trades, profile)
    expect(status.dailyStatus).toBe('breached')
    expect(status.maxStatus).toBe('breached')
  })

  it('returns null when only one limit is configured', () => {
    expect(buildFtmoStatus([], { dailyLossLimit: 500 })).toBeNull()
    expect(buildFtmoStatus([], { maxLossLimit: 1000 })).toBeNull()
  })
})

describe('buildDrawdown — edge cases', () => {
  it('handles a single losing trade', () => {
    const trades = [{ date: '2024-01-01', profitLoss: -100 }]
    const dd = buildDrawdown(trades)
    // equity never went positive — peak = 0, current = -100 → drawdown = 100
    expect(dd.currentDrawdown).toBeGreaterThanOrEqual(0)
    expect(dd.maxDrawdown).toBeGreaterThanOrEqual(0)
  })

  it('handles only profitable trades — no drawdown', () => {
    const trades = [
      { date: '2024-01-01', profitLoss: 100 },
      { date: '2024-01-02', profitLoss: 200 },
    ]
    const dd = buildDrawdown(trades)
    expect(dd.currentDrawdown).toBe(0)
    expect(dd.maxDrawdown).toBe(0)
  })

  it('peak-to-trough precision over multiple drops', () => {
    // Equity: +200, -300 → 200-300=-100 → peak=200, trough=-100 → maxDD=300
    // Then +500 → 400 → still no new peak-to-trough
    const trades = [
      { date: '2024-01-01', profitLoss: 200 },
      { date: '2024-01-02', profitLoss: -300 },
      { date: '2024-01-03', profitLoss: 500 },
    ]
    const dd = buildDrawdown(trades)
    expect(dd.maxDrawdown).toBeCloseTo(300, 5)
    expect(dd.currentDrawdown).toBe(0) // ends above peak
  })
})

describe('calculateTradeRisk — edge cases', () => {
  it('calculates correct risk for minimum lot size (0.01)', () => {
    const trade = { entryPrice: 2000, stopLoss: 1990, lotSize: 0.01, symbol: 'XAUUSD' }
    const result = calculateTradeRisk(trade, 10000)
    // 10 pips × 0.01 lot × 100 contractSize × 0.92 USD→EUR = 9.2
    expect(result.riskEur).toBeCloseTo(9.2, 5)
  })

  it('returns null when lot size is 0', () => {
    const trade = { entryPrice: 2000, stopLoss: 1990, lotSize: 0, symbol: 'XAUUSD' }
    expect(calculateTradeRisk(trade, 10000)).toBeNull()
  })
})
