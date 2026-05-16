@echo off
REM Start de autonomous XAUUSD bot in DEMO mode (MT5 demo account, geen echt geld)
cd /d %~dp0..
python scripts/run_live_bot.py --mode demo --log-level INFO
pause
