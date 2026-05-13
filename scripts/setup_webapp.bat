@echo off
REM Install dependencies for the imported Next.js trading journal
cd /d "%~dp0..\webapp"

if not exist package.json (
    echo ERROR: webapp\package.json not found.
    exit /b 1
)

echo Installing webapp dependencies...
npm install
