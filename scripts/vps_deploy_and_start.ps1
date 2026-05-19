# ============================================================
#  VPS DEPLOYMENT & STARTUP SCRIPT
#  Voer uit als Administrator op de VPS (PowerShell)
#
#  Stap 1: Kopieer de XAUUSD map naar C:\TradingBot\XAUUSD\
#  Stap 2: Open PowerShell als Admin
#  Stap 3: cd C:\TradingBot\XAUUSD
#  Stap 4: powershell -ExecutionPolicy Bypass -File scripts\vps_deploy_and_start.ps1
# ============================================================

$BotDir  = "C:\TradingBot\XAUUSD"
$LogDir  = "$BotDir\live_logs"
$VenvDir = "$BotDir\.venv"
$Python  = if (Test-Path "$VenvDir\Scripts\python.exe") { "$VenvDir\Scripts\python.exe" } else { "python" }

Write-Host "============================================================"
Write-Host "  XAUUSD VPS Deployment Script"
Write-Host "============================================================"
Write-Host ""

# 1. Check bot dir
if (-not (Test-Path $BotDir)) {
    Write-Host "FOUT: $BotDir bestaat niet. Kopieer de bot bestanden eerst." -ForegroundColor Red
    exit 1
}
Set-Location $BotDir

# 2. Maak log dir aan
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Write-Host "[OK] Log directory: $LogDir"

# 3. Check .env
if (-not (Test-Path "$BotDir\.env")) {
    Write-Host "FOUT: .env niet gevonden in $BotDir" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] .env gevonden"

# 4. Check Python
try {
    $pyver = & $Python --version 2>&1
    Write-Host "[OK] Python: $pyver"
} catch {
    Write-Host "FOUT: Python niet gevonden — installeer Python 3.10+" -ForegroundColor Red
    exit 1
}

# 5. Installeer dependencies als venv niet bestaat
if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host "Virtual environment aanmaken..."
    python -m venv $VenvDir
    & "$VenvDir\Scripts\pip.exe" install --upgrade pip --quiet
    & "$VenvDir\Scripts\pip.exe" install -r "$BotDir\requirements.txt" --quiet
    Write-Host "[OK] Dependencies geinstalleerd"
} else {
    Write-Host "[OK] Virtual environment gevonden"
}

# 6. Dry-run validatie
Write-Host ""
Write-Host "Pre-flight validatie uitvoeren..."
$result = & $Python "scripts\run_live_bot.py" --mode demo --dry-run 2>&1
Write-Host $result
if ($LASTEXITCODE -ne 0) {
    Write-Host "FOUT: Pre-flight mislukt — controleer .env" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Pre-flight geslaagd"

# 7. Verwijder stale lock
Remove-Item -Path "$LogDir\bot.lock" -ErrorAction SilentlyContinue
Write-Host "[OK] Lock file opgeruimd"

# 8. Installeer watchdog als Windows Scheduled Task
Write-Host ""
Write-Host "Watchdog installeren als Windows Scheduled Task..."
& powershell -ExecutionPolicy Bypass -File "$BotDir\scripts\install_watchdog.ps1"

# 9. Start de bot direct
Write-Host ""
Write-Host "Bot starten in achtergrond..."
Start-Process -FilePath $Python `
    -ArgumentList "scripts\run_live_bot.py --mode demo --log-level INFO" `
    -WorkingDirectory $BotDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$LogDir\bot_stdout.log" `
    -RedirectStandardError  "$LogDir\bot_stderr.log"

Start-Sleep -Seconds 5

# 10. Controleer of het process draait
$running = Get-Process -Name "python" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -eq "" }
if ($running) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  BOT ACTIEF — VPS deployment succesvol!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Logs bekijken:"
    Write-Host "  Get-Content $LogDir\bot_stdout.log -Wait"
    Write-Host ""
    Write-Host "Heartbeat bekijken:"
    Write-Host "  Get-Content $LogDir\heartbeat.json"
    Write-Host ""
    Write-Host "Bot stoppen:"
    Write-Host "  Stop-ScheduledTask -TaskName XAUUSD_Watchdog"
    Write-Host "  Stop-Process -Name python -Force"
} else {
    Write-Host "WAARSCHUWING: Process niet zichtbaar (kan in achtergrond draaien)" -ForegroundColor Yellow
    Write-Host "Controleer: Get-Content $LogDir\bot_stdout.log"
}
