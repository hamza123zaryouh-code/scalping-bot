import { promises as fs } from 'fs'
import path from 'path'
import { parse as parseEnv } from 'dotenv'

const BOT_API_BASE = process.env.BOT_API_BASE || 'http://127.0.0.1:8000/api/v1'
const DEV_START_COMMAND = 'python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000'
const ROOT_DIR = path.resolve(process.cwd(), '..')
const ENV_PATH = path.join(ROOT_DIR, '.env')
const STATE_PATH = path.join(ROOT_DIR, 'live_logs', 'bot_state.json')
const LOG_PATH = path.join(ROOT_DIR, 'live_logs', 'xauusd_live_bot.log')
const LOG_LINE_RE = /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+\|\s+([A-Z]+)\s+\|\s+([^|]+)\s+\|\s+(.*)$/
const ORDER_RE =
  /ORDER (POGING|UITGEVOERD) \| (LONG|SHORT) signal \| modus=([^|]+) \| volume=([\d.]+) \| prijs=([\d.]+) \| SL=([\d.]+) \| TP=([\d.]+) \| spread_buffer=([\d.]+) \| reden=(.+)$/i

async function safeReadText(filePath) {
  try {
    return await fs.readFile(filePath, 'utf-8')
  } catch {
    return ''
  }
}

async function safeReadJson(filePath) {
  try {
    const text = await fs.readFile(filePath, 'utf-8')
    return JSON.parse(text)
  } catch {
    return {}
  }
}

function parseIsoDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function minutesSince(value) {
  const date = parseIsoDate(value)
  if (!date) return null
  return Math.max(0, Math.round((Date.now() - date.getTime()) / 60000))
}

function structuredLogEntries(logText) {
  const entries = []

  for (const rawLine of logText.split(/\r?\n/)) {
    const line = rawLine.trimEnd()
    if (!line.trim()) continue

    const match = line.match(LOG_LINE_RE)
    if (match) {
      entries.push({
        timestamp: `${match[1].replace(' ', 'T')}`,
        level: match[2],
        source: match[3].trim(),
        message: match[4].trim(),
        lines: [],
      })
      continue
    }

    if (entries.length > 0) {
      entries[entries.length - 1].lines.push(line.trim())
    }
  }

  return entries.map((entry) => ({
    ...entry,
    fullMessage: [entry.message, ...entry.lines].join('\n').trim(),
  }))
}

function parseReportDetails(entry) {
  const lines = [entry.message, ...entry.lines]
  const detailMap = {}

  for (const line of lines) {
    const [label, value] = line.split(':')
    if (!value) continue
    detailMap[label.trim()] = value.trim()
  }

  return {
    title: lines[0] || 'Rapport',
    details: detailMap,
    lines,
  }
}

function parseOrderDetails(message) {
  const match = message.match(ORDER_RE)
  if (!match) return null

  return {
    phase: match[1].toLowerCase() === 'uitgevoerd' ? 'executed' : 'attempt',
    side: match[2].toLowerCase(),
    mode: match[3].trim(),
    volume: Number(match[4]),
    price: Number(match[5]),
    stopLoss: Number(match[6]),
    takeProfit: Number(match[7]),
    spreadBuffer: Number(match[8]),
    reason: match[9].trim(),
  }
}

function classifyLogEntry(entry) {
  const message = entry.message
  const fullMessage = entry.fullMessage
  const order = parseOrderDetails(message)

  if (order) {
    return {
      timestamp: entry.timestamp,
      type: order.phase === 'executed' ? 'order-executed' : 'order-attempt',
      tone: order.phase === 'executed' ? 'success' : 'warning',
      title: order.phase === 'executed' ? 'Order uitgevoerd' : 'Order poging',
      summary: `${order.side.toUpperCase()} | ${order.volume.toFixed(2)} lots | ${order.price.toFixed(2)}`,
      details: order,
      raw: fullMessage,
    }
  }

  if (message.includes('2-uurs rapport')) {
    return {
      timestamp: entry.timestamp,
      type: 'report',
      tone: 'info',
      title: '2-uurs rapport',
      summary: entry.lines[1] || entry.lines[0] || 'Bot statusrapport',
      details: parseReportDetails(entry),
      raw: fullMessage,
    }
  }

  if (/No new qualified signal/i.test(message)) {
    return {
      timestamp: entry.timestamp,
      type: 'signal-idle',
      tone: 'muted',
      title: 'Geen nieuw signaal',
      summary: 'Bot heeft geen nieuw gekwalificeerd signaal gevonden.',
      details: null,
      raw: fullMessage,
    }
  }

  if (/Spread-buffer toegepast/i.test(message)) {
    return {
      timestamp: entry.timestamp,
      type: 'risk-guardrail',
      tone: 'warning',
      title: 'Spread-buffer toegepast',
      summary: message,
      details: null,
      raw: fullMessage,
    }
  }

  if (/Lotsize capped/i.test(message)) {
    return {
      timestamp: entry.timestamp,
      type: 'risk-guardrail',
      tone: 'warning',
      title: 'Lotsize begrensd',
      summary: message,
      details: null,
      raw: fullMessage,
    }
  }

  if (entry.level === 'ERROR') {
    return {
      timestamp: entry.timestamp,
      type: 'error',
      tone: 'danger',
      title: 'Runtime fout',
      summary: message,
      details: null,
      raw: fullMessage,
    }
  }

  return {
    timestamp: entry.timestamp,
    type: 'info',
    tone: 'info',
    title: entry.level === 'WARNING' ? 'Waarschuwing' : 'Update',
    summary: message,
    details: null,
    raw: fullMessage,
  }
}

function analyzeLogText(logText, state) {
  const entries = structuredLogEntries(logText)
  const events = entries.map(classifyLogEntry)
  const orderEvents = events.filter((event) => event.type === 'order-executed')
  const attemptEvents = events.filter((event) => event.type === 'order-attempt')
  const reportEvent = [...events].reverse().find((event) => event.type === 'report') ?? null
  const lastOrder = orderEvents.at(-1) ?? null
  const heartbeatAgeMinutes = minutesSince(state?.last_heartbeat_time)

  return {
    metrics: {
      totalEntries: entries.length,
      noSignalCount: entries.filter((entry) => /No new qualified signal/i.test(entry.message)).length,
      reportCount: events.filter((event) => event.type === 'report').length,
      orderAttemptCount: attemptEvents.length,
      executedOrderCount: orderEvents.length,
      guardrailCount: events.filter((event) => event.type === 'risk-guardrail').length,
      errorCount: events.filter((event) => event.type === 'error').length,
      heartbeatAgeMinutes,
      lastOrderTime: lastOrder?.timestamp ?? null,
      lastOrderSide: lastOrder?.details?.side ?? null,
    },
    recentEvents: events.slice(-12).reverse(),
    latestReport: reportEvent,
    lastOrder,
  }
}

export async function loadBotEnv() {
  const envText = await safeReadText(ENV_PATH)
  const parsed = envText ? parseEnv(envText) : {}
  return {
    symbol: parsed.TRADING_SYMBOL || 'XAUUSD',
    timeframe: parsed.TRADING_TIMEFRAME || 'M1',
    mode: parsed.BOT_MODE || 'demo',
    checkIntervalSeconds: Number(parsed.CHECK_INTERVAL_SECONDS || 20),
    historyBars: Number(parsed.HISTORY_BARS || 350),
    riskPerTradePct: Number(parsed.RISK_PER_TRADE || 0.0025) * 100,
    slAtr: Number(parsed.STOP_LOSS_ATR_MULTIPLIER || 1.5),
    tpAtr: Number(parsed.TAKE_PROFIT_ATR_MULTIPLIER || 3.0),
    maxOpenPositions: Number(parsed.MAX_OPEN_POSITIONS || 1),
    maxSpreadPoints: Number(parsed.MAX_SPREAD_POINTS || 450),
    maxDailyLoss: Number(parsed.FTMO_MAX_DAILY_LOSS || 8000),
    maxTotalLoss: Number(parsed.FTMO_MAX_TOTAL_LOSS || 16000),
    sessionStartHour: Number(parsed.SESSION_START_HOUR || 3),
    sessionEndHour: Number(parsed.SESSION_END_HOUR || 17),
    cooldownMinutes: Number(parsed.DUPLICATE_SIGNAL_COOLDOWN_MINUTES || 5),
    minVolumeMultiplier: Number(parsed.MIN_VOLUME_MULTIPLIER || 1.1),
    heartbeatMinutes: Number(parsed.STATUS_HEARTBEAT_MINUTES || 180),
    orderComment: parsed.ORDER_COMMENT || 'FTMO XAUUSD Live Test',
  }
}

export async function loadBotFiles() {
  const [state, logText] = await Promise.all([safeReadJson(STATE_PATH), safeReadText(LOG_PATH)])
  const recentLogs = logText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-12)

  return {
    state,
    logText,
    recentLogs,
    analysis: analyzeLogText(logText, state),
  }
}

function buildUnavailableMessage(endpoint = '') {
  const target = endpoint ? `${BOT_API_BASE}${endpoint}` : BOT_API_BASE
  return `Bot backend is unavailable at ${target}. Start it with: ${DEV_START_COMMAND}`
}

export async function botApiGet(endpoint, accessToken, authRequired = true) {
  const headers =
    authRequired && accessToken
      ? { Authorization: `Bearer ${accessToken}` }
      : {}

  try {
    const response = await fetch(`${BOT_API_BASE}${endpoint}`, {
      headers,
      cache: 'no-store',
    })

    const data = await response.json().catch(() => null)
    return {
      ok: response.ok,
      status: response.status,
      data,
      error: response.ok ? null : data?.detail || data?.error || 'Request failed.',
    }
  } catch (error) {
    return {
      ok: false,
      status: 503,
      data: null,
      error: buildUnavailableMessage(endpoint),
      cause: error instanceof Error ? error.message : String(error),
    }
  }
}

export async function buildOverviewPayload(accessToken) {
  const [env, files, health, risk, live, signal, positions, analytics] = await Promise.all([
    loadBotEnv(),
    loadBotFiles(),
    botApiGet('/health', accessToken, false),
    botApiGet('/risk/status', accessToken, true),
    botApiGet('/dashboard/live', accessToken, true),
    botApiGet('/signals/live', accessToken, true),
    botApiGet('/signals/positions/open', accessToken, true),
    botApiGet('/analytics/metrics', accessToken, true),
  ])

  const backendUnavailable = !health.ok

  return {
    env,
    botState: files.state,
    recentLogs: files.recentLogs,
    logAnalysis: files.analysis,
    health: health.data ?? { status: backendUnavailable ? 'offline' : 'unknown' },
    risk,
    live,
    signal,
    positions,
    analytics,
    system: {
      botApiBase: BOT_API_BASE,
      backendUnavailable,
      healthError: health.error,
      startCommand: DEV_START_COMMAND,
      heartbeatAgeMinutes: files.analysis.metrics.heartbeatAgeMinutes,
    },
  }
}

export { BOT_API_BASE, DEV_START_COMMAND }
