# XAUUSD Expert Desk

Next.js operator webapp for the XAUUSD platform.

## Runtime expectations

- The FastAPI backend must be running
- The webapp trusts only backend-issued JWTs
- There is no local `alg:none` auth bypass anymore

## Environment

Typical `.env.local` or shared repo `.env` values:

```bash
BOT_API_BASE=http://127.0.0.1:8000/api/v1
BACKEND_JWT_SECRET=<same value as backend SECRET_KEY>
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
ALLOW_LOCAL_JOURNAL_FALLBACK=false
```

`BACKEND_JWT_SECRET` must stay separate from `SUPABASE_SERVICE_ROLE_KEY`.

## Run

```bash
npm install
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
npm run dev
```

Open `http://localhost:3000`.

Repo helper scripts still work:

- `scripts\run_api.bat`
- `scripts\run_webapp.bat`
- `scripts\run_dev_stack.bat`

## Login

Sign in with the backend admin account configured through:

- `AUTH_ADMIN_USERNAME`
- `AUTH_ADMIN_PASSWORD_HASH`

## Persistence modes

- Supabase mode: requires `NEXT_PUBLIC_SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- Local-only fallback: requires `ALLOW_LOCAL_JOURNAL_FALLBACK=true`
- If neither is configured, trade/profile/review routes return `503`
- Production rejects local fallback and requires an explicit shared JWT secret

## Manual Supabase smoke test

Run this once after applying `supabase/schema.sql` and starting the webapp:

```bash
python scripts/manual_trade_profile_crud_check.py
```

The script verifies authenticated profile CRUD plus trade create/list/update/delete through the Next.js API routes.
