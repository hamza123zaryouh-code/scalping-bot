export interface AccountInfo {
  balance: number;
  equity: number;
  floating_pnl: number;
  daily_pnl: number;
  drawdown_pct: number;
  drawdown_usd: number;
}

export interface PerformanceInfo {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  profit_factor: number;
  total_pnl: number;
}

export interface RiskInfo {
  daily_loss_limit: number;
  daily_loss_used: number;
  daily_loss_pct: number;
  total_loss_limit: number;
  total_loss_used: number;
  total_loss_pct: number;
  can_trade: boolean;
}

export interface ActivityInfo {
  open_positions: number;
  signals_today: number;
  ai_confidence: number;
  last_signal: string | null;
  bot_cycles: number;
}

export interface DashboardData {
  timestamp: string;
  mode: string;
  status: string;
  account: AccountInfo;
  performance: PerformanceInfo;
  risk: RiskInfo;
  activity: ActivityInfo;
}

export interface Position {
  ticket: number | string;
  symbol: string;
  side: string;
  volume: number;
  entry: number;
  current: number;
  sl: number;
  tp: number;
  profit: number;
  swap: number;
  duration_min: number;
}

export interface Trade {
  id: number;
  broker_ticket: string;
  symbol: string;
  side: string;
  mode: string;
  status: string;
  opened_at: string;
  closed_at: string | null;
  entry_price: number;
  exit_price: number | null;
  stop_loss: number;
  take_profit: number;
  volume: number;
  pnl: number | null;
  signal_type: string | null;
  reward_risk_ratio: number | null;
  atr: number | null;
  rsi: number | null;
  market_regime: string;
}

export interface TradeHistoryData {
  trades: Trade[];
  total: number;
  wins: number;
  losses: number;
  total_pnl: number;
  profit_factor: number;
  win_rate: number;
}

export interface EquityPoint {
  time: string;
  pnl: number;
  equity: number;
  cumulative_pnl: number;
}

export interface DrawdownPoint {
  time: string;
  drawdown_pct: number;
}

export interface MonthlyPnL {
  month: string;
  pnl: number;
  trades: number;
  win_rate: number;
}

export interface WeeklyBacktestSummary {
  week: string;
  week_start: string;
  trades: number;
  pnl: number;
  return_pct: number;
  start_equity: number;
  end_equity: number;
  win_rate: number;
}

export interface BacktestMetricsSummary {
  total_trades: number;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  total_return_pct: number;
  avg_win: number;
  avg_loss: number;
  expectancy: number;
  calmar_ratio: number;
  ftmo_passed: boolean;
  challenge_days: number;
}

export interface BacktestRunResult {
  task_id: string;
  metrics: BacktestMetricsSummary;
  trades: Array<{
    side: string;
    entry_time: string;
    exit_time: string;
    entry_price: number;
    exit_price: number;
    stop_loss: number;
    take_profit: number;
    size: number;
    pnl: number;
    cumulative_equity: number;
  }>;
  equity_curve: Array<{
    timestamp: string;
    capital: number;
    pnl: number;
  }>;
  monthly_summary: MonthlyPnL[];
  weekly_summary: WeeklyBacktestSummary[];
  chart_path?: string | null;
}

export interface BacktestHistoryItem {
  id?: number;
  task_id?: string;
  filename?: string;
  created?: string;
  created_at?: string;
  strategy?: string;
  total_return?: number;
  total_return_pct?: number;
  max_drawdown?: number;
  max_drawdown_pct?: number;
  sharpe_ratio?: number;
  win_rate?: number;
  profit_factor?: number;
  total_trades?: number;
  start_date?: string;
  end_date?: string;
  parameters?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SignalRecord {
  time: string;
  side: string;
  label?: string;
  reason?: string;
  atr?: number;
  confidence?: number;
}

export interface Pattern {
  type: string;
  count: number;
  avg_pnl: number;
  win_rate: number;
  conditions: Record<string, unknown>;
}

export interface ModelSnapshot {
  id: number;
  trained_at: string;
  sample_count: number;
  accuracy: number;
  precision: number;
  recall: number;
  f1_score: number;
  feature_importances: Record<string, number>;
}

export interface StrategyVersion {
  file: string;
  version: string;
  modified: string;
  size_bytes: number;
}

export interface SessionPerformance {
  session: string;
  total_pnl: number;
  count: number;
  win_rate: number;
}

export interface SignalTypeRanking {
  signal_type: string;
  total_pnl: number;
  count: number;
  wins: number;
  win_rate: number;
}

export interface FTMOStatus {
  can_trade: boolean;
  daily_loss_used: number;
  daily_loss_limit: number;
  daily_loss_pct: number;
  total_loss_used: number;
  total_loss_limit: number;
  total_loss_pct: number;
  phase: string;
  target_profit: number;
}

export interface APIResponse<T> {
  data: T;
  message?: string;
  error?: string;
}

export interface TelegramActionLog {
  id: number;
  telegram_user_id: string;
  telegram_username: string | null;
  action: string;
  status: string;
  details: Record<string, unknown>;
  created_at: string | null;
}

export interface ControlCommandRecord {
  id: number;
  command: string;
  status: string;
  requested_by: string;
  payload: Record<string, unknown>;
  source: string;
  result_message?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  executed_at?: string | null;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
  seq: number;
}

export interface CommandCenterData {
  timestamp: string;
  stream: {
    connected_clients: number;
    available_channels: string[];
    last_log_seq: number;
    heartbeat_present: boolean;
    heartbeat_age_seconds: number | null;
    stale: boolean;
    bot_state_present: boolean;
  };
  heartbeat: {
    status: string;
    trading_bot_running: boolean;
    ts: string;
    [key: string]: unknown;
  };
  runtime: {
    engine_status: Record<string, unknown>;
    control_state: {
      bot_active?: boolean;
      trading_paused?: boolean;
      signals_enabled?: boolean;
      emergency_stop?: boolean;
      updated_at?: string;
      [key: string]: unknown;
    };
    circuit_breaker: Record<string, unknown>;
    ftmo_guard: Record<string, unknown>;
    news_guard: Record<string, unknown>;
    sentiment: Record<string, unknown>;
    last_signal?: SignalRecord | null;
    open_positions: Position[];
  };
  telegram: {
    configured: boolean;
    owner_configured: boolean;
    api_key_configured: boolean;
    backend_base_url: string;
    recent_actions: TelegramActionLog[];
    recent_commands: ControlCommandRecord[];
  };
  news: {
    cache_present: boolean;
    danger_score: number;
    high_impact_count: number;
    composite_sentiment: number;
    should_pause_trading: boolean;
    top_keywords: string[];
  };
  logs: {
    records: LogEntry[];
    tail_file_available: boolean;
  };
}
