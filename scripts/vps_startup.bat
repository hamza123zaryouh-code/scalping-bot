@echo off
REM ============================================================
REM  XAUUSD Autonomous Trading Bot — VPS Auto-Start
REM  Plaats dit bestand als taak in Windows Task Scheduler:
REM    Trigger: At system startup
REM    Action : Start program → vps_startup.bat
REM    Options: Run whether user is logged on or not
REM ============================================================

title XAUUSD Trading Bot (DEMO)
cd /d %~dp0..

REM Wacht 30 seconden na boot zodat MT5 tijd heeft om te starten
timeout /t 30 /nobreak

REM Start MT5 (pas pad aan naar jouw MT5 installatie)
REM start "" "C:\Program Files\MetaTrader 5\terminal64.exe"
REM timeout /t 15 /nobreak

REM Activeer venv als die bestaat
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:restart
echo [%date% %time%] Starten van XAUUSD bot in DEMO mode...
python scripts/run_live_bot.py --mode demo --log-level INFO

echo [%date% %time%] Bot gestopt/gecrasht. Herstart in 10 seconden...
timeout /t 10 /nobreak
goto restart
