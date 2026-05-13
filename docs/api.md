# API Documentation

Base URL: `http://localhost:8000/api/v1`

## Authentication

All endpoints except `/health` and `/auth/token` require a JWT bearer token.

The backend credentials come from:

- `AUTH_ADMIN_USERNAME`
- `AUTH_ADMIN_PASSWORD_HASH`
- `SECRET_KEY`

Example login:

```bash
curl -X POST http://localhost:8000/api/v1/auth/token ^
  -d "username=<configured-admin-username>&password=<admin-password>"
```

Example authenticated request:

```bash
curl -H "Authorization: Bearer <token>" ^
  http://localhost:8000/api/v1/risk/status
```

## Auth Endpoints

### `POST /auth/token`

Returns:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "role": "admin"
}
```

## Backtest Endpoints

Backtest API routes are intentionally disabled in this build.

- `POST /backtest/run`
- `GET /backtest/status/{task_id}`
- `GET /backtest/result/{task_id}`

All three currently return:

- HTTP `503`
- `"Backtest functionality has been removed from this build."`

## Risk Endpoints

### `GET /risk/ftmo`

Query params:

- `equity`
- `day_start_equity`
- `estimated_trade_risk`

Response:

```json
{
  "success": true,
  "data": {
    "daily_buffer_pct": 100.0,
    "total_buffer_pct": 100.0,
    "risk_level": "green",
    "daily_ok": true,
    "total_ok": true,
    "overall_ok": true
  }
}
```

## Signal Endpoints

### `GET /signals/live`

Returns the latest evaluated signal, or `null` when none is available.

### `GET /signals/positions/open`

Returns open MT5 positions visible to the backend.

## Analytics Endpoints

### `GET /analytics/metrics`

Returns the aggregated autonomous-engine analytics report.

### `GET /analytics/monthly`

Returns monthly rollups.

### `GET /analytics/session`

Returns session/hour breakdowns.

### `GET /analytics/regime`

Returns regime performance breakdowns.

### `GET /analytics/sentiment`

Returns the latest stored sentiment snapshot.

### `GET /analytics/ml`

Returns model snapshot history.

If the analytics database is unavailable, analytics routes now return HTTP `503` instead of pretending the request succeeded.

## Report Endpoints

### `GET /reports/list`

Lists PDF, PNG and CSV artefacts available for download.

### `GET /reports/download/{filename}`

Downloads a specific artefact. Path traversal attempts are rejected with HTTP `400`.
