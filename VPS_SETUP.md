# VPS Setup Guide — XAUUSD Trading Bot

## Vereisten VPS
- **Windows VPS** (MT5 draait alleen op Windows)
- Minimaal: 2 CPU cores, 4 GB RAM, 50 GB SSD
- Aanbevolen: Contabo Windows VPS (~€7-10/mnd) of Hetzner (Linux + Wine als alternatief)

---

## Stap 1: Python installeren
1. Download Python 3.10: https://www.python.org/downloads/release/python-3100/
2. Installeer met "Add to PATH" aangevinkt
3. Controleer: `python --version`

## Stap 2: Project uploaden naar VPS
**Optie A — ZIP via Remote Desktop:**
1. Maak zip van de hele `XAUUSD` map (exclusief `node_modules`, `.next`)
2. Kopieer via RDP (Remote Desktop) naar VPS bijv. naar `C:\TradingBot\XAUUSD`

**Optie B — Git:**
```
git clone https://github.com/jouw-repo/XAUUSD.git C:\TradingBot\XAUUSD
```

## Stap 3: Dependencies installeren
Open CMD in `C:\TradingBot\XAUUSD`:
```cmd
pip install -r requirements.txt
pip install python-telegram-bot python-dotenv MetaTrader5
```

## Stap 4: .env configureren
Het `.env` bestand staat al correct ingesteld:
- `AUTONOMOUS_MODE=demo` (demo account)
- `MT5_LOGIN=1513372223`
- `MT5_SERVER=FTMO-Demo`
- Telegram token + chat ID ingesteld

Voor live trading later:
- Verander `AUTONOMOUS_MODE=demo` naar `live`
- Update `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`

## Stap 5: MetaTrader 5 installeren
1. Download MT5 van FTMO: https://ftmo.com/mt5/
2. Installeer en log in met demo account: `1513372223` op `FTMO-Demo`
3. Laat MT5 open staan (minimized)

## Stap 6: Bot starten (handmatig testen)
```cmd
cd C:\TradingBot\XAUUSD
python scripts/run_live_bot.py --mode demo --log-level INFO
```

Controleer Telegram: je ontvangt een bericht "Autonomous XAUUSD systeem gestart in demo mode"
Stuur daarna `/start` aan @HamzaFTMOBot voor het control menu met knoppen.

## Stap 7: Auto-start via Windows Task Scheduler
1. Open **Task Scheduler** (zoek in Start menu)
2. Klik "Create Task"
3. Instellingen:
   - **Name:** XAUUSD Trading Bot
   - **Security:** Run whether user is logged on or not + Run with highest privileges
   - **Trigger:** At system startup (delay 1 minute)
   - **Action:** Start program
     - Program: `C:\TradingBot\XAUUSD\scripts\vps_startup.bat`
     - Start in: `C:\TradingBot\XAUUSD`
4. Klik OK, voer VPS wachtwoord in

## Stap 8: Logs controleren
```cmd
type C:\TradingBot\XAUUSD\live_logs\bot_stdout.log
type C:\TradingBot\XAUUSD\live_logs\runtime.log
```

---

## Telegram commando's
Na het sturen van `/start` aan @HamzaFTMOBot:

| Knop | Functie |
|------|---------|
| 📊 Dashboard | Account status, equity, PnL |
| ⚙️ Bot Control | Start/stop/pause bot |
| 🛡 Risk Control | Daily risk, FTMO status |
| 📡 Signals | Actieve signalen, confidence |
| 🧠 AI Memory | Train model, setup stats |
| 🧪 Backtest | Quick backtest vanuit Telegram |
| 📄 Reports | Daily/weekly/monthly rapport |

---

## Live account overschakelen
Alleen 3 dingen aanpassen in `.env`:
```
AUTONOMOUS_MODE=live
MT5_LOGIN=jouw_live_account_nummer
MT5_PASSWORD=jouw_live_wachtwoord
MT5_SERVER=FTMO-Live4  (of jouw FTMO live server naam)
```
Alles andere (risk, lot size, FTMO limieten) blijft hetzelfde.

---

## Troubleshooting

**Bot start niet / MT5 verbinding mislukt:**
- Controleer of MT5 open staat en ingelogd is
- Zorg dat `Allow automated trading` aan staat in MT5
- Check: Tools → Options → Expert Advisors → Allow algorithmic trading

**Geen Telegram berichten:**
- Stuur eerst `/start` naar @HamzaFTMOBot
- Controleer of `TELEGRAM_BOT_TOKEN` en `TELEGRAM_CHAT_ID` kloppen in .env
- Test: `python scripts/test_telegram_buttons.py`

**Bot crasht bij start:**
- Check logs: `type live_logs\bot_stdout.log`
- Meest voorkomend: MT5 niet open, of verkeerde MT5 login
