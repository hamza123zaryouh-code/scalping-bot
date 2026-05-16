@echo off
REM Start de autonomous XAUUSD bot in PAPER mode (veilig, geen echte trades)
cd /d %~dp0..
python scripts/run_live_bot.py --mode paper --log-level INFO
pause
