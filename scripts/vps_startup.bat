@echo off
REM ============================================================
REM  XAUUSD Autonomous Trading Bot — VPS Auto-Start
REM  Symbolen: XAUUSD + EURUSD + GBPUSD (V22 multi-symbol)
REM
REM  Installatie in Windows Task Scheduler:
REM    Trigger : At system startup
REM    Action  : Start program -> vps_startup.bat
REM    Options : Run whether user is logged on or not
REM              Run with highest privileges
REM ============================================================

title XAUUSD V22 Bot (3 symbolen)
cd /d %~dp0..

REM Wacht 60 seconden zodat MT5 tijd heeft om op te starten
timeout /t 60 /nobreak

REM Start MT5 automatisch — pas pad aan naar jouw installatie
start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
timeout /t 25 /nobreak

REM Activeer virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Zet multi-symbool omgeving (overschrijft .env als nodig)
set AUTONOMOUS_SYMBOLS=XAUUSD,EURUSD,GBPUSD

:restart
echo [%date% %time%] Starten van V22 bot (XAUUSD/EURUSD/GBPUSD) in DEMO/LIVE mode...
python scripts/run_live_bot.py --mode demo --log-level INFO

echo [%date% %time%] Bot gestopt/gecrasht. Herstart over 15 seconden...
timeout /t 15 /nobreak
goto restart
