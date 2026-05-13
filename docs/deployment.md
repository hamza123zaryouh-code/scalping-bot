# Deployment Guide

## Required environment

Production deployments must provide:

- `APP_ENV=production`
- `SECRET_KEY`
- `AUTH_ADMIN_USERNAME`
- `AUTH_ADMIN_PASSWORD_HASH`
- `CORS_ORIGINS`

Optional but common:

- `POSTGRES_URL` or `SUPABASE_DB_URL` for the autonomous runtime database
- `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` for webapp journal persistence
- `BACKEND_JWT_SECRET` in the webapp runtime, set to the same value as the backend `SECRET_KEY`
- `BOT_MODE=demo` or `BOT_MODE=live`
- `ALLOW_LIVE_ACCOUNT=true` when running live

## Local Windows development

```bat
scripts\setup.bat
scripts\run_api.bat
scripts\run_dashboard.bat
scripts\run_webapp.bat
```

Optional:

```bat
python monitoring\watchdog.py
python -m autonomous_xauusd.init_db
```

## Docker

```bash
docker-compose -f deployment/docker-compose.yml up -d --build
docker-compose -f deployment/docker-compose.yml logs -f
docker-compose -f deployment/docker-compose.yml down
```

## Windows service

```bat
nssm install XAUUSDApi "C:\...\XAUUSD\.venv\Scripts\python.exe" "-m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
nssm set XAUUSDApi AppDirectory "C:\...\XAUUSD"
nssm start XAUUSDApi
```

## Schema provisioning

### Autonomous database

- Managed from `autonomous_xauusd/memory_layer.py`
- Bootstrap once before first production run:

```bash
python -m autonomous_xauusd.init_db
```

### Supabase journal tables

- Apply `webapp/supabase/schema.sql`
- Preferred automation: `python scripts/apply_supabase_schema.py`
- The schema is server-mediated and uses `public.app_users`
- Do not rely on direct browser writes to these tables
- Keep `SUPABASE_SERVICE_ROLE_KEY` separate from the shared JWT secret
- The webapp production runtime must set `BACKEND_JWT_SECRET` or `JWT_SHARED_SECRET` explicitly instead of relying on a `SECRET_KEY` fallback

### Supabase CRUD smoke test

- Start the webapp with the Supabase env vars configured
- Run `python scripts/manual_trade_profile_crud_check.py`
- The script signs a backend-compatible JWT locally, then verifies profile and trade CRUD through the Next.js API routes

## CORS and auth notes

- The backend refuses to start in production without `CORS_ORIGINS`
- The backend refuses to start in production without `SECRET_KEY`
- Demo-style implicit credentials are no longer allowed
- The webapp verifies backend JWTs server-side before accepting a session cookie
- The webapp production runtime rejects `ALLOW_LOCAL_JOURNAL_FALLBACK=true`

## TLS / reverse proxy

Terminate TLS in Nginx or another reverse proxy before exposing the API publicly.
