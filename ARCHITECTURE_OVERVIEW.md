# Architecture Overview — XAUUSD Trading Platform
**Versie:** V16 (production) → V17 (in ontwikkeling)  
**Datum:** 2026-05-14

---

## Systeemoverzicht

```
┌─────────────────────────────────────────────────────────┐
│                    XAUUSD Trading Platform               │
├──────────────┬──────────────────┬───────────────────────┤
│   FRONTEND   │     BACKEND      │   AUTONOMOUS ENGINE   │
│  Next.js 15  │   FastAPI 0.111  │  autonomous_xauusd/   │
│  React 19    │   Python 3.10+   │  Python 3.10+         │
│  Tailwind 4  │   SQLAlchemy 2   │  PostgreSQL via ORM   │
│  Recharts 3  │   JWT Auth       │  MT5 + yfinance       │
│  TypeScript  │   WebSocket      │  Telegram Bot         │
└──────────────┴──────────────────┴───────────────────────┘
```

---

## Mappenstructuur

```
XAUUSD/
├── backend/                    # FastAPI REST + WebSocket server
│   ├── main.py                 # App factory, CORS, WebSocket handler
│   ├── api/
│   │   ├── routes/             # 10 route modules
│   │   │   ├── auth.py         # JWT token generatie
│   │   │   ├── dashboard.py    # Live dashboard + equity/drawdown curves
│   │   │   ├── analytics.py    # Analytics endpoints
│   │   │   ├── signals.py      # Trading signals
│   │   │   ├── risk.py         # Risk management
│   │   │   ├── reports.py      # Rapport listing & download
│   │   │   ├── trading.py      # Trade execution
│   │   │   ├── memory.py       # Memory layer queries
│   │   │   ├── optimizer.py    # Parameter optimalisatie
│   │   │   └── backtest.py     # UITGESCHAKELD (503 responses)
│   │   ├── schemas/            # Pydantic request/response models
│   │   └── deps.py             # Dependency injection (auth)
│   ├── core/
│   │   ├── config.py           # Settings via pydantic-settings
│   │   ├── logging.py          # Structlog setup
│   │   └── security.py         # JWT encode/decode, password hashing
│   ├── services/
│   │   ├── signal_service.py   # Signal business logic
│   │   ├── risk_service.py     # Risk calculaties
│   │   └── backtest_service.py # Backtest service (disabled)
│   └── websocket/
│       └── manager.py          # WebSocket connection manager
│
├── autonomous_xauusd/          # Autonome trading engine
│   ├── main.py                 # AutonomousTradingSystem runner
│   ├── memory_layer.py         # SQLAlchemy ORM + persistente state
│   ├── data_layer.py           # Market data (MT5/yfinance/ccxt)
│   ├── brain_layer.py          # ML/intelligence layer
│   ├── analytics_engine.py     # Rapportberekeningen
│   ├── sentiment_layer.py      # Markt sentiment analyse
│   ├── communication_layer.py  # Telegram control interface
│   ├── dashboard_layer.py      # Streamlit autonomous dashboard
│   ├── models.py               # Pydantic models
│   ├── settings.py             # Config loader
│   └── init_db.py              # Database schema initialisatie
│
├── webapp/                     # Next.js 15 Control Center
│   └── src/
│       ├── app/                # App Router pages
│       │   ├── dashboard/      # Live trading dashboard
│       │   ├── backtest/       # Backtest viewer
│       │   ├── analytics/      # Performance analytics
│       │   ├── reports/        # Rapport download
│       │   ├── optimizer/      # Parameter optimizer
│       │   ├── trading/        # Trade management
│       │   ├── risk/           # Risk center
│       │   ├── ai-memory/      # Strategy memory viewer
│       │   └── login/          # Auth
│       ├── components/
│       │   ├── layout/         # AppShell, Sidebar, TopBar
│       │   ├── charts/         # DrawdownChart, EquityChart, MonthlyPnLChart
│       │   └── ui/             # Alert, Badge, Card, Spinner
│       └── lib/
│           ├── api.ts          # API client (fetch wrapper)
│           ├── types.ts        # TypeScript types
│           └── hooks/          # useAutoRefresh, useWebSocket
│
├── strategy_v7.py → v16.py     # Strategie versies (referentie + productie)
├── strategy_v16.py             # ACTIEVE productie strategie (V16)
├── xauusd_backtest.py          # Backtest runner (46 KB)
├── xauusd_bot.py               # Live bot runner (26 KB)
├── indicators.py               # Technische indicatoren (EMA, RSI, ATR, ADX)
├── risk_manager.py             # FTMO risk management
├── config.py                   # Bot configuratie loader
│
├── tests/                      # Test suite
│   ├── unit/                   # 8 unit tests
│   ├── integration/            # 3 integration tests
│   ├── regression/             # 1 backtest regression
│   └── smoke/                  # 1 pipeline smoke test
│
├── configs/                    # YAML configs (default/development/production)
├── deployment/                 # Docker + nginx
├── monitoring/                 # Health check + watchdog
├── scripts/                    # Startup .bat scripts + utility Python scripts
├── memory/                     # Strategy memory (JSON/CSV)
├── exports/                    # Backtest archieven (93 MB)
├── results/                    # Optimizer resultaten (7.8 MB)
├── reports/                    # Equity curves + PnL charts (0.9 MB)
└── logs/ + live_logs/          # Runtime logs
```

---

## Data Flow

```
MarktData (MT5/yfinance)
        │
        ▼
  data_layer.py
        │
        ▼
  brain_layer.py ──── sentiment_layer.py
        │
        ▼
  strategy_v16.py (signaal generatie)
        │
        ▼
  risk_manager.py (positie sizing, FTMO limieten)
        │
        ▼
  memory_layer.py (PostgreSQL — trades opslaan)
        │
        ├──► analytics_engine.py (rapporten)
        ├──► communication_layer.py (Telegram alerts)
        └──► backend/api/ (REST API → webapp)
                          │
                          ▼
                   webapp/ (Next.js dashboard)
```

---

## API Endpoints (`/api/v1/`)

| Prefix | Module | Status |
|--------|--------|--------|
| `/auth` | auth.py | Actief |
| `/dashboard` | dashboard.py | Actief |
| `/risk` | risk.py | Actief |
| `/signals` | signals.py | Actief |
| `/analytics` | analytics.py | Actief |
| `/trading` | trading.py | Actief |
| `/memory` | memory.py | Actief |
| `/optimizer` | optimizer.py | Actief |
| `/reports` | reports.py | Actief |
| `/backtest` | backtest.py | **Uitgeschakeld (503)** |
| `/ws/live` | main.py WebSocket | Actief |
| `/api/docs` | FastAPI Swagger | Actief |

---

## Technology Stack

| Laag | Technologie | Versie |
|------|-------------|--------|
| Frontend framework | Next.js | 15.0.0 |
| Frontend UI | React | 19.2.4 |
| Styling | Tailwind CSS | 4 |
| Charting | Recharts | 3.2.1 |
| Language (frontend) | TypeScript | 5 |
| Backend framework | FastAPI | ≥0.111 |
| Language (backend) | Python | ≥3.10 |
| ORM | SQLAlchemy | ≥2.0 |
| Database | PostgreSQL | (via psycopg3) |
| Auth | python-jose (JWT) | ≥3.3 |
| Market data (live) | MetaTrader5 | ≥5.0 (Windows) |
| Market data (backtest) | yfinance | ≥0.2.36 |
| Containerisatie | Docker | via deployment/ |
| Telegram | python-telegram-bot | ≥21.6 |

---

## FTMO Compliance Parameters (V16)

| Parameter | Waarde |
|-----------|--------|
| Startkapitaal | €160,000 |
| Max dagelijks verlies | €8,000 (5%) |
| Max totaal verlies | €16,000 (10%) |
| Max drawdown bereikt (V16) | 2.83% |
| Gemiddeld maandinkomen | €8,923 – €9,964 |
| Signalen per dag | ~2 |
| Signaaltypen | 6 |
