@echo off
REM Start the FastAPI backend and Next.js webapp in separate terminals.
set ROOT=%~dp0..

start "XAUUSD API" cmd /k "cd /d %ROOT% && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000"
start "XAUUSD Webapp" cmd /k "cd /d %ROOT%\webapp && npm run dev"

echo Started API and webapp in separate windows.
