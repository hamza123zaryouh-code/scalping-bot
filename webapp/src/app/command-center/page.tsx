"use client";

import { startTransition, useCallback, useState } from "react";
import { AppShell } from "../../components/layout/AppShell";
import { Alert } from "../../components/ui/Alert";
import { Badge, LiveBadge, ModeBadge } from "../../components/ui/Badge";
import { Card, KPICard } from "../../components/ui/Card";
import { PageLoader } from "../../components/ui/Spinner";
import { api } from "../../lib/api";
import { useAutoRefresh } from "../../lib/hooks/useAutoRefresh";
import { useWebSocket, type WebSocketMessage } from "../../lib/hooks/useWebSocket";
import type { CommandCenterData, DashboardData, LogEntry, Position, SignalRecord } from "../../lib/types";

const LIVE_CHANNELS = ["equity", "positions", "trades", "risk", "regime", "heartbeat", "sentiment", "news", "execution"];

type EventTapeItem = {
  id: string;
  type: string;
  label: string;
  detail: string;
  at: string;
  tone: "green" | "red" | "blue" | "yellow" | "gray";
};

function fmtMoney(value: number) {
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
  }).format(value);
}

function fmtPercent(value: number, digits = 1) {
  return `${value.toFixed(digits)}%`;
}

function fmtTime(value: string | null | undefined) {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString();
}

function relativeAge(seconds: number | null) {
  if (seconds === null) return "unknown";
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

function summarizeMessage(msg: WebSocketMessage): EventTapeItem {
  const payload = (msg.payload ?? {}) as Record<string, unknown>;
  const at = typeof msg.ts === "string" ? msg.ts : new Date().toISOString();

  if (msg.type === "equity.update") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Equity pulse",
      detail: `Equity ${fmtMoney(Number(payload.equity ?? 0))}, drawdown ${fmtPercent(Number(payload.drawdown_pct ?? 0), 2)}.`,
      at,
      tone: Number(payload.drawdown_pct ?? 0) > 3 ? "yellow" : "green",
    };
  }

  if (msg.type === "positions.update") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Positions sync",
      detail: `${Number(payload.count ?? 0)} open positions, floating PnL ${fmtMoney(Number(payload.floating_pnl ?? 0))}.`,
      at,
      tone: Number(payload.count ?? 0) > 0 ? "blue" : "gray",
    };
  }

  if (msg.type === "signal.detected") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Signal detected",
      detail: `${String(payload.symbol ?? "XAUUSD")} ${String(payload.side ?? "unknown").toUpperCase()} ${String(payload.reason ?? "signal")}.`,
      at,
      tone: String(payload.side ?? "").toLowerCase() === "sell" ? "red" : "green",
    };
  }

  if (msg.type === "execution.update") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Execution state",
      detail: `Status ${String(payload.status ?? "unknown")}, ${Number(payload.open_positions ?? 0)} open, paused ${Boolean(payload.trading_paused) ? "yes" : "no"}.`,
      at,
      tone: Boolean(payload.emergency_stop) ? "red" : "blue",
    };
  }

  if (msg.type === "risk.update") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Risk update",
      detail: `Daily loss ${fmtMoney(Number(payload.daily_loss ?? 0))}, multiplier ${Number(payload.risk_multiplier ?? 1).toFixed(2)}x.`,
      at,
      tone: Boolean(payload.circuit_breaker_active) ? "red" : "yellow",
    };
  }

  if (msg.type === "heartbeat") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Heartbeat",
      detail: `Runtime ${String(payload.status ?? "unknown")}, bot running ${Boolean(payload.trading_bot_running) ? "yes" : "no"}.`,
      at,
      tone: Boolean(payload.trading_bot_running) ? "green" : "gray",
    };
  }

  if (msg.type === "news.update") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "News risk",
      detail: `Danger score ${Number(payload.danger_score ?? 0).toFixed(2)}, pause ${Boolean(payload.should_pause) ? "yes" : "no"}.`,
      at,
      tone: Boolean(payload.should_pause) ? "red" : "yellow",
    };
  }

  if (msg.type === "sentiment.update") {
    return {
      id: `${at}-${msg.type}`,
      type: msg.type,
      label: "Sentiment",
      detail: `${String(payload.label ?? "neutral")} at ${Number(payload.score ?? 0).toFixed(2)}.`,
      at,
      tone: Number(payload.score ?? 0) >= 0 ? "green" : "red",
    };
  }

  return {
    id: `${at}-${msg.type}`,
    type: msg.type,
    label: msg.type,
    detail: "Live event received from the stream.",
    at,
    tone: "gray",
  };
}

function severityBadgeColor(level: string) {
  if (level === "ERROR" || level === "CRITICAL") return "red";
  if (level === "WARNING") return "yellow";
  if (level === "SIGNAL" || level === "TRADE") return "blue";
  return "gray";
}

function PositionStrip({ positions }: { positions: Position[] }) {
  if (!positions.length) {
    return <p style={{ fontSize: 12, color: "var(--text-muted)" }}>No open positions currently tracked by runtime.</p>;
  }

  return (
    <div className="feed-list">
      {positions.slice(0, 4).map((position, index) => (
        <div key={`${position.ticket}-${index}`} className="feed-item">
          <div className="feed-item-header">
            <div className="feed-item-title">
              <Badge variant={position.side === "buy" ? "green" : "red"}>{position.side.toUpperCase()}</Badge>
              <span>{position.symbol}</span>
            </div>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>ticket {position.ticket}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
            <div>
              <div className="metric-chip-label">Volume</div>
              <div className="surface-value">{Number(position.volume ?? 0).toFixed(2)}</div>
            </div>
            <div>
              <div className="metric-chip-label">Entry</div>
              <div className="surface-value">{Number((position as unknown as { entry_price?: number }).entry_price ?? position.entry ?? 0).toFixed(2)}</div>
            </div>
            <div>
              <div className="metric-chip-label">Current</div>
              <div className="surface-value">{Number(position.current ?? 0).toFixed(2)}</div>
            </div>
            <div>
              <div className="metric-chip-label">Profit</div>
              <div
                className="surface-value"
                style={{ color: Number(position.profit ?? 0) >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}
              >
                {fmtMoney(Number(position.profit ?? 0))}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function runtimeFlag(active: boolean, trueText: string, falseText: string) {
  return <Badge variant={active ? "green" : "gray"}>{active ? trueText : falseText}</Badge>;
}

export default function CommandCenterPage() {
  const dashboardFetcher = useCallback(() => api.dashboard(), []);
  const controlFetcher = useCallback(() => api.commandCenter(), []);
  const logsFetcher = useCallback(() => api.recentLogs(40), []);

  const { data: dashboardRes, loading: dashboardLoading, error: dashboardError } = useAutoRefresh(dashboardFetcher, 8000);
  const { data: controlRes, loading: controlLoading, error: controlError } = useAutoRefresh(controlFetcher, 8000);
  const { data: logsRes } = useAutoRefresh(logsFetcher, 12000);
  const [eventTape, setEventTape] = useState<EventTapeItem[]>([]);

  const handleMessage = useCallback((msg: WebSocketMessage) => {
    startTransition(() => {
      setEventTape((current) => [summarizeMessage(msg), ...current].slice(0, 18));
    });
  }, []);

  const { connected, connectionState, lastMessage, reconnectCount } = useWebSocket({
    channels: LIVE_CHANNELS,
    onMessage: handleMessage,
  });

  if (dashboardLoading || controlLoading) {
    return <AppShell><PageLoader /></AppShell>;
  }

  if (dashboardError || controlError) {
    return (
      <AppShell>
        <Alert type="error" title="Command Center unavailable">
          {dashboardError || controlError || "Could not load the command center snapshot."}
        </Alert>
      </AppShell>
    );
  }

  const dashboard = (dashboardRes as { data: DashboardData } | null)?.data;
  const control = (controlRes as { data: CommandCenterData } | null)?.data;
  const recentLogs = ((logsRes as { data: { records: LogEntry[] } } | null)?.data?.records ?? control?.logs.records ?? []);

  if (!dashboard || !control) {
    return <AppShell><PageLoader /></AppShell>;
  }

  const runtime = control.runtime;
  const stream = control.stream;
  const telegram = control.telegram;
  const heartbeat = control.heartbeat;
  const engineStatus = runtime.engine_status as Record<string, unknown>;
  const controlState = runtime.control_state;
  const circuitBreaker = runtime.circuit_breaker as Record<string, unknown>;
  const sentiment = runtime.sentiment as Record<string, unknown>;
  const newsGuard = runtime.news_guard as Record<string, unknown>;
  const heartbeatState = Boolean(heartbeat.trading_bot_running);
  const liveStatusTone = stream.stale ? "red" : connected ? "green" : "yellow";
  const positions = runtime.open_positions ?? [];

  return (
    <AppShell mode={dashboard.mode} lastUpdate={control.timestamp}>
      <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <section className="hero-panel" style={{ padding: 22 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
            <div style={{ maxWidth: 760 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
                <Badge variant="blue">Expert Ops</Badge>
                <ModeBadge mode={dashboard.mode} />
                <LiveBadge active={connected} />
                <Badge variant={telegram.configured ? "green" : "yellow"}>
                  Telegram {telegram.configured ? "ready" : "partial"}
                </Badge>
              </div>
              <h2 style={{ fontSize: 28, lineHeight: 1.1, letterSpacing: "-0.03em", marginBottom: 10 }}>
                XAUUSD mission control for live execution, Telegram oversight and stream telemetry.
              </h2>
              <p style={{ maxWidth: 640, color: "var(--text-secondary)", fontSize: 14, lineHeight: 1.6 }}>
                This view combines live risk, bot runtime, stream health, operator actions and the last event pulses into one command layer.
              </p>
            </div>
            <div className="metric-strip">
              <div className="metric-chip">
                <div className="metric-chip-label">Heartbeat</div>
                <div className="metric-chip-value">{relativeAge(stream.heartbeat_age_seconds)}</div>
              </div>
              <div className="metric-chip">
                <div className="metric-chip-label">WS Clients</div>
                <div className="metric-chip-value">{stream.connected_clients}</div>
              </div>
              <div className="metric-chip">
                <div className="metric-chip-label">Reconnects</div>
                <div className="metric-chip-value">{reconnectCount}</div>
              </div>
              <div className="metric-chip">
                <div className="metric-chip-label">Last Event</div>
                <div className="metric-chip-value" style={{ fontSize: 16 }}>{lastMessage?.type ?? "awaiting"}</div>
              </div>
            </div>
          </div>
        </section>

        {(stream.stale || !telegram.configured || !dashboard.risk.can_trade) && (
          <Alert type={stream.stale || !dashboard.risk.can_trade ? "warning" : "info"} title="Operator attention">
            {!dashboard.risk.can_trade
              ? "FTMO or internal risk guard is blocking trading. Review circuit breaker and news lock status before resuming."
              : stream.stale
                ? "The heartbeat looks stale. Verify the live bot process and watchdog before trusting the stream."
                : "Telegram is not fully configured yet. Monitoring still works, but remote operator control may be incomplete."}
          </Alert>
        )}

        <div className="command-grid">
          <div className="command-span-3">
            <KPICard label="Equity" value={fmtMoney(dashboard.account.equity)} sub={`Balance ${fmtMoney(dashboard.account.balance)}`} color="default" icon="EQ" />
          </div>
          <div className="command-span-3">
            <KPICard
              label="Daily PnL"
              value={fmtMoney(dashboard.account.daily_pnl)}
              sub={`${fmtPercent(dashboard.risk.daily_loss_pct)} of FTMO daily limit`}
              color={dashboard.account.daily_pnl >= 0 ? "green" : "red"}
              trend={dashboard.account.daily_pnl >= 0 ? "up" : "down"}
              icon="DY"
            />
          </div>
          <div className="command-span-3">
            <KPICard
              label="Risk State"
              value={String(circuitBreaker.risk_level ?? dashboard.risk.ftmo_status ?? "NORMAL")}
              sub={`CB ${Boolean(circuitBreaker.circuit_breaker_active) ? "active" : "clear"}`}
              color={Boolean(circuitBreaker.circuit_breaker_active) ? "red" : "yellow"}
              icon="RS"
            />
          </div>
          <div className="command-span-3">
            <KPICard
              label="Stream Health"
              value={stream.stale ? "STALE" : connected ? "LIVE" : connectionState.toUpperCase()}
              sub={`Heartbeat ${relativeAge(stream.heartbeat_age_seconds)}`}
              color={liveStatusTone}
              icon="WS"
            />
          </div>

          <Card title="Execution Matrix" subtitle="Runtime, controls and market context" className="command-span-4" glow="blue">
            <div className="surface-list">
              <div className="surface-row"><span className="surface-label">Engine status</span><span className="surface-value">{String(engineStatus.status ?? "unknown")}</span></div>
              <div className="surface-row"><span className="surface-label">Symbol / timeframe</span><span className="surface-value">{String(engineStatus.symbol ?? "XAUUSD")} {String(engineStatus.timeframe ?? "M15")}</span></div>
              <div className="surface-row"><span className="surface-label">Bot active</span><span className="surface-value">{runtimeFlag(Boolean(controlState.bot_active), "running", "stopped")}</span></div>
              <div className="surface-row"><span className="surface-label">Trading paused</span><span className="surface-value">{runtimeFlag(Boolean(controlState.trading_paused), "paused", "live")}</span></div>
              <div className="surface-row"><span className="surface-label">Signals enabled</span><span className="surface-value">{runtimeFlag(Boolean(controlState.signals_enabled), "enabled", "disabled")}</span></div>
              <div className="surface-row"><span className="surface-label">Emergency stop</span><span className="surface-value">{runtimeFlag(Boolean(controlState.emergency_stop), "armed", "clear")}</span></div>
              <div className="surface-row"><span className="surface-label">Open positions</span><span className="surface-value">{positions.length}</span></div>
              <div className="surface-row"><span className="surface-label">Last signal</span><span className="surface-value">{fmtTime((runtime.last_signal as SignalRecord | null)?.time)}</span></div>
            </div>
          </Card>

          <Card title="Risk, News and Sentiment" subtitle="FTMO, circuit breaker and macro posture" className="command-span-4" glow="red">
            <div className="surface-list">
              <div className="surface-row"><span className="surface-label">FTMO trading state</span><span className="surface-value"><Badge variant={dashboard.risk.can_trade ? "green" : "red"}>{dashboard.risk.can_trade ? "allowed" : "blocked"}</Badge></span></div>
              <div className="surface-row"><span className="surface-label">Daily loss used</span><span className="surface-value">{fmtMoney(dashboard.risk.daily_loss_used)} / {fmtMoney(dashboard.risk.daily_loss_limit)}</span></div>
              <div className="surface-row"><span className="surface-label">Total drawdown</span><span className="surface-value">{fmtMoney(dashboard.risk.total_loss_used)} / {fmtMoney(dashboard.risk.total_loss_limit)}</span></div>
              <div className="surface-row"><span className="surface-label">News lock</span><span className="surface-value"><Badge variant={Boolean(newsGuard.allow_trading ?? true) ? "green" : "red"}>{Boolean(newsGuard.allow_trading ?? true) ? "clear" : "locked"}</Badge></span></div>
              <div className="surface-row"><span className="surface-label">News danger</span><span className="surface-value">{Number(control.news.danger_score ?? 0).toFixed(2)}</span></div>
              <div className="surface-row"><span className="surface-label">Sentiment</span><span className="surface-value">{String(sentiment.label ?? "neutral")} ({Number(sentiment.score ?? 0).toFixed(2)})</span></div>
              <div className="surface-row"><span className="surface-label">Top keywords</span><span className="surface-value">{control.news.top_keywords.join(", ") || "--"}</span></div>
            </div>
          </Card>

          <Card title="Telegram Operator Deck" subtitle="Remote control readiness and audit trail" className="command-span-4" glow="green">
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
              <Badge variant={telegram.configured ? "green" : "yellow"}>bot {telegram.configured ? "ready" : "partial"}</Badge>
              <Badge variant={telegram.owner_configured ? "green" : "yellow"}>owner {telegram.owner_configured ? "set" : "missing"}</Badge>
              <Badge variant={telegram.api_key_configured ? "green" : "yellow"}>api key {telegram.api_key_configured ? "set" : "missing"}</Badge>
            </div>
            <div className="surface-list">
              <div className="surface-row"><span className="surface-label">Backend base URL</span><span className="surface-value">{telegram.backend_base_url || "--"}</span></div>
              <div className="surface-row"><span className="surface-label">Recent actions</span><span className="surface-value">{telegram.recent_actions.length}</span></div>
              <div className="surface-row"><span className="surface-label">Command queue items</span><span className="surface-value">{telegram.recent_commands.length}</span></div>
            </div>
            <div className="feed-list" style={{ marginTop: 14 }}>
              {telegram.recent_actions.slice(0, 4).map((action) => (
                <div key={action.id} className="feed-item">
                  <div className="feed-item-header">
                    <div className="feed-item-title">
                      <Badge variant={action.status === "denied" || action.status === "rejected" ? "red" : "blue"}>{action.status}</Badge>
                      <span>{action.action}</span>
                    </div>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{fmtTime(action.created_at)}</span>
                  </div>
                  <div className="feed-item-summary">user {action.telegram_username || action.telegram_user_id}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Live Event Tape" subtitle="WebSocket stream across execution, risk and signal channels" className="command-span-7">
            <div className="feed-list">
              {eventTape.length === 0 && <div className="feed-item"><div className="feed-item-summary">Awaiting live stream traffic from subscribed channels.</div></div>}
              {eventTape.map((event) => (
                <div key={event.id} className="feed-item">
                  <div className="feed-item-header">
                    <div className="feed-item-title">
                      <Badge variant={event.tone}>{event.label}</Badge>
                      <span>{event.type}</span>
                    </div>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{fmtTime(event.at)}</span>
                  </div>
                  <div className="feed-item-summary">{event.detail}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Stream and Runtime Health" subtitle="Heartbeat, process state and websocket transport" className="command-span-5">
            <div className="surface-list">
              <div className="surface-row"><span className="surface-label">Transport</span><span className="surface-value"><LiveBadge active={connected} /></span></div>
              <div className="surface-row"><span className="surface-label">Connection state</span><span className="surface-value">{connectionState}</span></div>
              <div className="surface-row"><span className="surface-label">Heartbeat status</span><span className="surface-value">{String(heartbeat.status ?? "unknown")}</span></div>
              <div className="surface-row"><span className="surface-label">Bot running</span><span className="surface-value">{runtimeFlag(heartbeatState, "yes", "no")}</span></div>
              <div className="surface-row"><span className="surface-label">Heartbeat age</span><span className="surface-value">{relativeAge(stream.heartbeat_age_seconds)}</span></div>
              <div className="surface-row"><span className="surface-label">Log sequence</span><span className="surface-value">{stream.last_log_seq}</span></div>
              <div className="surface-row"><span className="surface-label">Channels</span><span className="surface-value">{stream.available_channels.length}</span></div>
              <div className="surface-row"><span className="surface-label">Last heartbeat</span><span className="surface-value">{fmtTime(heartbeat.ts)}</span></div>
            </div>
          </Card>

          <Card title="Open Position Radar" subtitle={`${positions.length} runtime positions in focus`} className="command-span-5">
            <PositionStrip positions={positions} />
          </Card>

          <Card title="Recent Logs" subtitle="Buffered operator log stream" className="command-span-7">
            <div className="feed-list">
              {recentLogs.slice(-12).reverse().map((record) => (
                <div key={record.seq} className="feed-item">
                  <div className="feed-item-header">
                    <div className="feed-item-title">
                      <Badge variant={severityBadgeColor(record.level)}>{record.level}</Badge>
                      <span>{record.logger}</span>
                    </div>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{fmtTime(record.timestamp)}</span>
                  </div>
                  <div className="feed-item-summary">{record.message}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
