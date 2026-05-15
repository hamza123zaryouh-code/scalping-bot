# TELEGRAM BOT BUTTONS REPORT

## Overview

De Telegram bot is uitgebreid naar een production-ready control interface met:

- Inline keyboard hoofdmenu en submenu's
- Echte callback handlers voor alle buttons
- Koppeling aan echte FastAPI endpoints onder `/api/v1/telegram/*`
- Owner-only permissiecontrole via `TELEGRAM_OWNER_USER_ID`
- Database audit logging voor Telegram acties
- Confirmatieflow voor gevaarlijke acties
- Realtime status, risk, signal, AI memory, backtest en reports

## Main Menu

- `🤖 XAUUSD AI Trading Bot`
- `📊 Dashboard`
- `⚙️ Bot Control`
- `🛡 Risk Control`
- `📡 Signals`
- `🧠 AI Memory`
- `🧪 Backtest`
- `📄 Reports`

## Dashboard Buttons

- `Account Status`
- `Equity`
- `Balance`
- `Open PnL`
- `Daily PnL`
- `Weekly PnL`
- `Monthly PnL`
- `Drawdown`
- `FTMO Status`

Backend:

- `GET /api/v1/telegram/status`

## Bot Control Buttons

- `Start Bot`
- `Stop Bot`
- `Pause Trading`
- `Resume Trading`
- `Emergency Stop`
- `Close All Positions`

Backend:

- `POST /api/v1/telegram/control/start_bot`
- `POST /api/v1/telegram/control/stop_bot`
- `POST /api/v1/telegram/control/pause_trading`
- `POST /api/v1/telegram/control/resume_trading`
- `POST /api/v1/telegram/control/emergency_stop`
- `POST /api/v1/telegram/control/close_all_positions`

Implementation notes:

- Control acties worden in `control_commands` gequeued
- De draaiende autonome engine verwerkt de queue zelf
- `Close All Positions` sluit echte paper- of MT5-posities via de engine
- `Start/Stop/Pause/Resume` wijzigen gedeelde runtime control state

## Risk Control Buttons

- `Daily Risk Status`
- `Weekly Risk Status`
- `Monthly Target Status`
- `Drawdown Check`
- `Loss Streak Check`
- `FTMO Rules Check`

Backend:

- `GET /api/v1/telegram/risk/daily`
- `GET /api/v1/telegram/risk/weekly`
- `GET /api/v1/telegram/risk/monthly_target`
- `GET /api/v1/telegram/risk/drawdown`
- `GET /api/v1/telegram/risk/loss_streak`
- `GET /api/v1/telegram/risk/ftmo_rules`

## Signals Buttons

- `Latest Signal`
- `Signal Confidence`
- `Signals Today`
- `Enable Signals`
- `Disable Signals`

Backend:

- `GET /api/v1/telegram/signals/latest`
- `GET /api/v1/telegram/signals/confidence`
- `GET /api/v1/telegram/signals/today`
- `POST /api/v1/telegram/signals/toggle`

Implementation notes:

- Signal toggles wijzigen runtime state `signals_enabled`
- Nieuwe signalen worden in `last_signal` en `signal_history` opgeslagen

## Backtest Buttons

- `Run Quick Backtest`
- `Latest Backtest Result`
- `Compare V16 vs V17`
- `Show Equity Curve Summary`

Backend:

- `POST /api/v1/telegram/backtest/quick-run`
- `GET /api/v1/telegram/backtest/latest`
- `GET /api/v1/telegram/backtest/compare`
- `GET /api/v1/telegram/backtest/equity-curve-summary`

## AI Memory Buttons

- `Train AI`
- `Show Best Setups`
- `Show Losing Setups`
- `Optimizer Status`
- `Learning Progress`

Backend:

- `POST /api/v1/telegram/memory/train`
- `GET /api/v1/telegram/memory/best_setups`
- `GET /api/v1/telegram/memory/losing_setups`
- `GET /api/v1/telegram/memory/optimizer_status`
- `GET /api/v1/telegram/memory/learning_progress`

Implementation notes:

- `Train AI` wordt als echte control command gequeued
- Best/losing setups worden uit `memory/winning_setups.json` en `memory/failed_setups.json` gelezen

## Reports Buttons

- `Daily Report`
- `Weekly Report`
- `Monthly Report`
- `Export Trade Log`

Backend:

- `GET /api/v1/telegram/reports/daily`
- `GET /api/v1/telegram/reports/weekly`
- `GET /api/v1/telegram/reports/monthly`
- `POST /api/v1/telegram/reports/export-trade-log`

Implementation notes:

- Trade log export maakt een echte CSV in `reports/`

## Security

- Alleen de geconfigureerde `TELEGRAM_OWNER_USER_ID` mag buttons gebruiken
- Backend machine-auth gebruikt `X-API-Key`
- Telegram control gebruikt `TELEGRAM_CONTROL_API_KEY`, anders `API_KEY`, anders `SECRET_KEY`
- Gevaarlijke acties vereisen confirmatie met `Yes/No`

## Database Changes

Toegevoegd in `autonomous_xauusd.memory_layer`:

- `control_commands`
- `telegram_action_logs`

Doelen:

- Queueing van control commands
- Audit logging van Telegram interacties

## Runtime / Engine Changes

- Nieuwe gedeelde `bot_control` runtime state
- Autonome engine verwerkt control commands tijdens runtime
- Engine blijft online als `Stop Bot` wordt gebruikt, zodat `Start Bot` later via Telegram kan hervatten
- `Pause Trading` blokkeert nieuwe trades maar houdt monitoring actief
- `Emergency Stop` zet trading direct in veilige stopstatus

## Files Added or Updated

- `autonomous_xauusd/communication_layer.py`
- `autonomous_xauusd/main.py`
- `autonomous_xauusd/data_layer.py`
- `autonomous_xauusd/memory_layer.py`
- `autonomous_xauusd/settings.py`
- `backend/api/deps.py`
- `backend/api/routes/telegram.py`
- `backend/api/schemas/telegram.py`
- `backend/core/config.py`
- `backend/main.py`
- `backend/services/telegram_service.py`
- `tests/integration/test_telegram_api.py`
- `tests/unit/test_telegram_control_layer.py`

## Tests Executed

Command:

```powershell
pytest tests\integration\test_telegram_api.py tests\unit\test_telegram_control_layer.py -q
```

Validated:

- All Telegram endpoint routes
- API key protection
- Permission denial for non-owner users
- Dangerous action confirmation flow
- Confirmed control action execution
- Signal toggle state updates
- Trade log export
- Quick backtest endpoint wiring

Result:

- `10 passed`

## Required Environment Variables

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_OWNER_USER_ID`
- `TELEGRAM_CONTROL_API_KEY` recommended

Optional fallback auth:

- `API_KEY`
- `SECRET_KEY`
