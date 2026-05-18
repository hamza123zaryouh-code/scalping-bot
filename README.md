# XAUUSD Trading Platform

Production-oriented XAUUSD trading workspace with:

- FastAPI backend for auth, analytics, reports, risk and live bot APIs
- Next.js webapp for operator workflows
- Streamlit dashboards
- Autonomous engine with its own SQLAlchemy-backed runtime database

## Current production baseline

- Backend auth is JWT-based and requires `SECRET_KEY`, `AUTH_ADMIN_USERNAME` and `AUTH_ADMIN_PASSWORD_HASH`
- The webapp only trusts server-verified backend JWTs
- Insecure `alg: none` login fallback has been removed
- WebSocket `/ws/live` now requires auth and no longer rebroadcasts arbitrary client payloads
- Backtest API routes are fully implemented under `/api/v1/backtest/*`
- Analytics no longer perform database initialization in the request path

## Architecture and data flows

### Backend auth flow

1. `POST /api/v1/auth/token` validates the configured admin credentials.
2. FastAPI signs an access token with `SECRET_KEY`.
3. Protected REST routes and `/ws/live` validate that JWT before serving data.

### Webapp session flow

1. The login page posts credentials to `webapp/src/app/api/auth/login/route.js`.
2. That route proxies the FastAPI auth endpoint.
3. The returned JWT is verified server-side before it is stored in the `bot-access-token` cookie.
4. Subsequent webapp API routes use `requireAuthenticatedUser()` to rebuild the operator context.

### Persistence flow

The webapp now has explicit persistence modes:

- `supabase`: enabled only when `NEXT_PUBLIC_SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are configured
- `local`: enabled only when `ALLOW_LOCAL_JOURNAL_FALLBACK=true`
- `unconfigured`: trade/profile/review routes fail with `503` instead of silently changing storage backends

Supabase writes are mediated by the server using an `app_users` table. The backend JWT subject is mapped to a stable UUID so the journal tables do not depend on Supabase Auth users.

### Autonomous database flow

- Source of truth: SQLAlchemy models in `autonomous_xauusd/memory_layer.py`
- Provisioning points: backend startup, autonomous engine startup, or `python -m autonomous_xauusd.init_db`
- Request handlers do not run schema DDL

## Setup

### 1. Python environment

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in at minimum:

```env
APP_ENV=development
SECRET_KEY=replace-with-a-random-32-plus-char-secret
AUTH_ADMIN_USERNAME=admin
AUTH_ADMIN_PASSWORD_HASH=<passlib-password-hash>
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:8501
```

Example password hash generation:

```bash
python -c "from backend.core.security import hash_password; print(hash_password('replace-me'))"
```

### 3. Optional webapp persistence settings

Choose one:

- Supabase mode:
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - Run `webapp/supabase/schema.sql`
- Explicit local-only mode:
  - `ALLOW_LOCAL_JOURNAL_FALLBACK=true`

### 4. Start services

```bash
scripts\run_api.bat
scripts\run_dashboard.bat
scripts\run_webapp.bat
```

Useful URLs:

- API docs: `http://localhost:8000/api/docs`
- Streamlit dashboard: `http://localhost:8501`
- Webapp: `http://localhost:3000`
- Health: `http://localhost:8000/api/v1/health`

## Schema management

### Autonomous runtime database

- Uses SQLAlchemy metadata from `autonomous_xauusd/memory_layer.py`
- Bootstrap with:

```bash
python -m autonomous_xauusd.init_db
```

### Supabase journal schema

- Uses `webapp/supabase/schema.sql`
- Apply it manually in the Supabase SQL editor
- This schema now uses `public.app_users` instead of `auth.users`

## Testing

Python:

```bash
pytest tests/unit tests/integration tests/regression tests/smoke
```

Webapp:

```bash
cd webapp
npm test
```

## Disabled / intentionally removed

- Public registration stays disabled in this workspace

## Backtest API

Backtest endpoints under `/api/v1/backtest/*` are fully supported. Use `POST /api/v1/backtest/run` for synchronous runs or `POST /api/v1/backtest/run-async` for async execution with WebSocket progress tracking.

## Operational notes

- Production startup fails if required auth or CORS settings are missing
- `BOT_MODE=live` requires `ALLOW_LIVE_ACCOUNT=true`
- Keep `.env`, service-role keys and MT5 credentials out of version control
