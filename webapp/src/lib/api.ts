const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let _token: string | null = null;

export function setToken(t: string | null) {
  _token = t;
  if (typeof window !== "undefined") {
    if (t) localStorage.setItem("xauusd_token", t);
    else localStorage.removeItem("xauusd_token");
  }
}

export function getToken(): string | null {
  if (_token) return _token;
  if (typeof window !== "undefined") {
    _token = localStorage.getItem("xauusd_token");
  }
  return _token;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    setToken(null);
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }

  return res.json();
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/api/v1/auth/token", {
      method: "POST",
      body: new URLSearchParams({ username, password }).toString(),
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }),

  // Dashboard
  dashboard: () => request<{ data: import("./types").DashboardData }>("/api/v1/dashboard/live"),
  equityCurve: () => request<{ data: { points: import("./types").EquityPoint[]; starting_capital: number } }>("/api/v1/dashboard/equity-curve"),
  monthlyPnL: () => request<{ data: { months: import("./types").MonthlyPnL[] } }>("/api/v1/dashboard/monthly-pnl"),
  drawdownCurve: () => request<{ data: { points: import("./types").DrawdownPoint[] } }>("/api/v1/dashboard/drawdown-curve"),

  // Trading
  positions: () => request<{ data: { positions: import("./types").Position[]; count: number; floating_pnl: number; equity: number; balance: number } }>("/api/v1/trading/positions"),
  tradeHistory: (limit = 100) => request<{ data: import("./types").TradeHistoryData }>(`/api/v1/trading/history?limit=${limit}`),
  exposure: () => request<{ data: unknown }>("/api/v1/trading/exposure"),
  signalsToday: () => request<{ data: { signals: import("./types").SignalRecord[]; count: number; buy_count: number; sell_count: number } }>("/api/v1/trading/signals/today"),

  // Risk
  riskStatus: () => request<{ data: unknown }>("/api/v1/risk/status"),
  ftmoStatus: (equity?: number, dayStart?: number) =>
    request<{ data: unknown }>(`/api/v1/risk/ftmo?equity=${equity ?? 160000}&day_start_equity=${dayStart ?? 160000}`),

  // Analytics
  analyticsMetrics: () => request<{ data: unknown }>("/api/v1/analytics/metrics"),
  analyticsMonthly: () => request<{ data: unknown }>("/api/v1/analytics/monthly"),
  analyticsSession: () => request<{ data: unknown }>("/api/v1/analytics/session"),
  analyticsRegime: () => request<{ data: unknown }>("/api/v1/analytics/regime"),
  analyticsML: () => request<{ data: import("./types").ModelSnapshot[] }>("/api/v1/analytics/ml"),

  // Backtest
  runBacktest: (payload: {
    start_date: string;
    end_date: string;
    starting_capital: number;
    risk_per_trade?: number;
    sl_atr_multiplier?: number;
    tp_atr_multiplier?: number;
    max_open_trades?: number;
    commission?: number;
    spread_cost?: number;
    symbol?: string;
    strategy_params?: Record<string, unknown>;
  }) => request<{ data: import("./types").BacktestRunResult }>("/api/v1/backtest/run", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  latestBacktest: () => request<{ data: import("./types").BacktestRunResult }>("/api/v1/backtest/latest"),
  backtestHistory: () => request<{ data: import("./types").BacktestHistoryItem[] }>("/api/v1/backtest/history"),

  // Memory
  patterns: () => request<{ data: { winning_patterns: unknown; losing_patterns: unknown; best_parameters: unknown } }>("/api/v1/memory/patterns"),
  trainingData: () => request<{ data: unknown }>("/api/v1/memory/training-data"),
  modelHistory: () => request<{ data: { snapshots: import("./types").ModelSnapshot[]; total: number } }>("/api/v1/memory/model-history"),
  strategyEvolution: () => request<{ data: { versions: import("./types").StrategyVersion[]; total: number; latest: string; notes: string } }>("/api/v1/memory/strategy-evolution"),
  runtimeState: () => request<{ data: unknown }>("/api/v1/memory/runtime-state"),

  // Optimizer
  bestParameters: () => request<{ data: unknown }>("/api/v1/optimizer/best-parameters"),
  optimizationHistory: () => request<{ data: { runs: import("./types").BacktestHistoryItem[]; total: number } }>("/api/v1/optimizer/history"),
  performanceRanking: () => request<{ data: { ranking: import("./types").SignalTypeRanking[] } }>("/api/v1/optimizer/performance-ranking"),
  sessionAnalysis: () => request<{ data: { sessions: import("./types").SessionPerformance[] } }>("/api/v1/optimizer/session-analysis"),

  // Health
  health: () => request<{ status: string; version: string; env: string }>("/api/v1/health"),
};
