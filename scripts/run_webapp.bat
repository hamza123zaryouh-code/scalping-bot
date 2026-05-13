@echo off
REM Start the imported Next.js trading journal
cd /d "%~dp0..\webapp"

if not exist package.json (
    echo ERROR: webapp\package.json not found.
    exit /b 1
)

echo Starting webapp on http://localhost:3000...
echo If login shows backend unavailable, start the API separately with scripts\run_api.bat
echo If Next dev starts throwing missing .next files, try npm run dev:webpack inside webapp
echo.

npm run dev
