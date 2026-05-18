# ============================================================
#  XAUUSD Trading Bot - VPS Deploy Script
#  Gebruik: PowerShell -ExecutionPolicy Bypass -File vps_deploy.ps1 -BotDir "C:\TradingBot\XAUUSD_VPS"
# ============================================================

param(
    [string]$BotDir = "C:\bots\XAUUSD",
    [string]$ServiceName = "XAUUSDBot",
    [string]$NssmPath = "C:\nssm\nssm.exe"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n[$msg]" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# 1. Bot directory
Write-Step "1/7 Bot directory controleren"
if (-not (Test-Path $BotDir)) {
    Write-Error "Map '$BotDir' niet gevonden."
    exit 1
}
Write-OK "Bot map gevonden: $BotDir"

# 2. Python
Write-Step "2/7 Python controleren"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "  Python niet gevonden, installeren via winget..."
    winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $py = Get-Command python -ErrorAction SilentlyContinue
}
Write-OK "Python: $($py.Source)"

# 3. Virtual environment
Write-Step "3/7 Virtual environment aanmaken"
$venv = Join-Path $BotDir ".venv"
if (-not (Test-Path $venv)) {
    python -m venv $venv
    Write-OK "Venv aangemaakt: $venv"
}
if (Test-Path $venv) {
    Write-OK "Venv klaar: $venv"
}

$pip  = Join-Path $venv "Scripts\pip.exe"
$pyex = Join-Path $venv "Scripts\python.exe"

# 4. Dependencies
Write-Step "4/7 Dependencies installeren (3-5 min)"
& $pip install --upgrade pip --quiet
& $pip install -e "$BotDir" --quiet
Write-OK "Dependencies geinstalleerd"

# 5. .env
Write-Step "5/7 .env controleren"
$envFile = Join-Path $BotDir ".env"
$envExample = Join-Path $BotDir ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
    }
    Write-Warn ".env aangemaakt - vul je credentials in: notepad $envFile"
    notepad $envFile
    Write-Host "  Druk ENTER als je klaar bent met invullen..." -ForegroundColor Yellow
    Read-Host
}
Write-OK ".env aanwezig"

# 6. Mappen
Write-Step "6/7 Log-mappen aanmaken"
foreach ($d in @("live_logs","logs","exports\latest","exports\history","datasets\raw")) {
    $full = Join-Path $BotDir $d
    if (-not (Test-Path $full)) {
        New-Item -ItemType Directory -Force $full | Out-Null
    }
}
Write-OK "Mappen klaar"

# 7. NSSM Service
Write-Step "7/7 Bot installeren als Windows Service"

if (-not (Test-Path $NssmPath)) {
    Write-Host "  NSSM downloaden..."
    $zip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "$env:TEMP\nssm_tmp" -Force
    New-Item -ItemType Directory -Force "C:\nssm" | Out-Null
    Copy-Item "$env:TEMP\nssm_tmp\nssm-2.24\win64\nssm.exe" $NssmPath
    Remove-Item "$env:TEMP\nssm_tmp" -Recurse -Force
    Write-OK "NSSM geinstalleerd"
}

# Verwijder bestaande service
$status = & $NssmPath status $ServiceName 2>&1
if ($status -notmatch "does not exist") {
    Write-Host "  Bestaande service verwijderen..."
    & $NssmPath stop $ServiceName 2>&1 | Out-Null
    & $NssmPath remove $ServiceName confirm 2>&1 | Out-Null
}

# Installeer service
& $NssmPath install $ServiceName $pyex "scripts\run_live_bot.py --mode live"
& $NssmPath set $ServiceName AppDirectory $BotDir
& $NssmPath set $ServiceName AppStdout (Join-Path $BotDir "live_logs\service_stdout.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $BotDir "live_logs\service_stderr.log")
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath start $ServiceName

$finalStatus = & $NssmPath status $ServiceName 2>&1
Write-OK "Service status: $finalStatus"

Write-Host "`n================================================" -ForegroundColor Green
Write-Host "  XAUUSD Bot succesvol gedeployed!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Logs bekijken:"
Write-Host "    Get-Content '$BotDir\live_logs\bot_stdout.log' -Tail 50 -Wait"
Write-Host ""
Write-Host "  Service beheren:"
Write-Host "    & '$NssmPath' status $ServiceName"
Write-Host "    & '$NssmPath' stop   $ServiceName"
Write-Host "    & '$NssmPath' start  $ServiceName"
