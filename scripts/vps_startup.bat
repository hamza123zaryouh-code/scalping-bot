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
REM
REM  MODUS: Leest AUTONOMOUS_MODE uit .env (demo of live)
REM  Om live te wisselen: zet AUTONOMOUS_MODE=live in .env
REM  Geen .env wijziging nodig in dit script.
REM ============================================================

title XAUUSD V22 Bot (XAUUSD/EURUSD/GBPUSD)
cd /d %~dp0..

REM ── 1. Logging setup ───────────────────────────────────────
if not exist "live_logs" mkdir live_logs
echo [%date% %time%] VPS startup gestart >> live_logs\vps_startup.log

REM ── 2. Wacht zodat Windows services opstarten ──────────────
echo Wachten 90 seconden voor systeemstart...
timeout /t 90 /nobreak

REM ── 3. Start MT5 terminal ──────────────────────────────────
REM Pas dit pad aan naar jouw MT5 installatie op de VPS
set MT5_EXE=C:\Program Files\MetaTrader 5\terminal64.exe
if exist "%MT5_EXE%" (
    echo MT5 starten: %MT5_EXE%
    start "" "%MT5_EXE%"
    timeout /t 30 /nobreak
) else (
    echo [WARN] MT5 niet gevonden op %MT5_EXE% >> live_logs\vps_startup.log
    echo [WARN] Controleer het MT5 pad in scripts\vps_startup.bat
)

REM ── 4. Activeer Python virtual environment ─────────────────
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [OK] .venv geactiveerd
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] venv geactiveerd
) else (
    echo [WARN] Geen virtual environment gevonden — gebruik systeem Python
)

REM ── 5. Multi-symbool zekerstellen ──────────────────────────
set AUTONOMOUS_SYMBOLS=XAUUSD,EURUSD,GBPUSD

REM ── 6. Bot starten met automatische herstart ───────────────
:restart
echo.
echo [%date% %time%] Bot starten (XAUUSD/EURUSD/GBPUSD)...
echo [%date% %time%] Bot starten >> live_logs\vps_startup.log

REM Lees modus uit .env — geen --mode argument nodig, run_live_bot.py leest AUTONOMOUS_MODE
python scripts/run_live_bot.py --log-level INFO

set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] Bot gestopt met code %EXIT_CODE%
echo [%date% %time%] Bot gestopt code=%EXIT_CODE% >> live_logs\vps_startup.log

REM Herstart na crash (niet na bewust stoppen via lock-file / SIGTERM)
if %EXIT_CODE% NEQ 0 (
    echo Herstart over 20 seconden...
    timeout /t 20 /nobreak
    goto restart
) else (
    echo Bot is netjes gestopt (exit code 0). Geen herstart.
    pause
)
