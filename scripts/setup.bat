@echo off
REM ─────────────────────────────────────────────────────────
REM  XAUUSD Trading Platform — Windows Setup Script
REM ─────────────────────────────────────────────────────────

echo.
echo  ===============================================
echo   XAUUSD Trading Platform — Setup
echo  ===============================================
echo.

REM Check Python version
python --version 2>NUL
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python is not installed or not in PATH.
    exit /b 1
)

REM Create virtual environment
echo [1/5] Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat

REM Upgrade pip
echo [2/5] Upgrading pip...
python -m pip install --upgrade pip

REM Install project + dev dependencies
echo [3/5] Installing dependencies...
pip install -e ".[dev]"

REM Copy .env.example if .env does not exist
echo [4/5] Setting up environment file...
IF NOT EXIST .env (
    copy .env.example .env
    echo   .env created from .env.example — fill in your credentials.
) ELSE (
    echo   .env already exists — skipping.
)

REM Create required directories
echo [5/5] Creating directories...
for %%D in (logs live_logs exports\latest exports\history exports\reports datasets\raw datasets\cleaned datasets\processed) do (
    if not exist %%D mkdir %%D
)

echo.
echo  ===============================================
echo   Setup complete!
echo.
echo   Quick start:
echo     1. Edit .env with your credentials
echo     2. Start API:        python -m uvicorn backend.main:app --reload
echo     3. Start Dashboard:  streamlit run frontend\app.py
echo     4. Run tests:        pytest tests\
echo  ===============================================
echo.
