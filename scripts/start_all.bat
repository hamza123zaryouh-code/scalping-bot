@echo off
title XAUUSD Trading System
cd /d C:\TradingBot\XAUUSD

REM Wacht 60 seconden na boot zodat MT5 tijd heeft om te starten
timeout /t 60 /nobreak

REM Start Backend API in apart venster
start "XAUUSD Backend API" cmd /k "cd /d C:\TradingBot\XAUUSD && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

REM Wacht 5 seconden zodat backend klaar is
timeout /t 5 /nobreak

REM Start Trading Bot met auto-herstart
:restart
echo [%date% %time%] XAUUSD bot starten...
python scripts/run_live_bot.py --mode demo --log-level INFO
echo [%date% %time%] Bot gestopt. Herstart in 10 seconden...
timeout /t 10 /nobreak
goto restart
