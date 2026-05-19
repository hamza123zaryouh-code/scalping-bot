# ============================================================
#  XAUUSD VPS ONE-CLICK SETUP
#  Voer uit als Administrator op de VPS in PowerShell
#  Doet alles automatisch: download, installeer, watchdog, start
# ============================================================

$BotDir     = "C:\TradingBot\XAUUSD"
$LogDir     = "$BotDir\live_logs"
$ZipUrl     = "https://api.telegram.org/file/bot8757076306:AAELjx_KSypJYS0C_O-u_D8ur-jfgzs4rVM/documents/file_0.zip"
$ZipPath    = "$env:TEMP\XAUUSD_VPS.zip"
$TaskName   = "XAUUSD_Bot_Watchdog"
$TgToken    = "8757076306:AAELjx_KSypJYS0C_O-u_D8ur-jfgzs4rVM"
$TgChat     = "5921087860"

function Send-Telegram($msg) {
    try {
        $body = @{ chat_id = $TgChat; text = $msg } | ConvertTo-Json
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$TgToken/sendMessage" `
            -Method POST -Body $body -ContentType "application/json" -TimeoutSec 15 | Out-Null
    } catch {}
}

function Log($msg) {
    $ts = (Get-Date).ToString("HH:mm:ss")
    Write-Host "[$ts] $msg"
}

Log "=== XAUUSD VPS ONE-CLICK SETUP ==="
Send-Telegram "VPS setup gestart op $(hostname)"

# 1. Python check
Log "Python controleren..."
$python = $null
foreach ($p in @("python", "python3", "C:\Python311\python.exe", "C:\Python310\python.exe")) {
    if (Get-Command $p -ErrorAction SilentlyContinue) { $python = $p; break }
}
if (-not $python) {
    Log "Python niet gevonden — installeren via winget..."
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    $env:PATH += ";C:\Users\Administrator\AppData\Local\Programs\Python\Python311"
    $python = "python"
}
$pyver = & $python --version 2>&1
Log "Python: $pyver"

# 2. Download bot
Log "Bot downloaden van Telegram..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipPath -TimeoutSec 120
$sizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Log "Download klaar ($sizeMB MB)"

# 3. Uitpakken
Log "Uitpakken naar $BotDir..."
if (Test-Path $BotDir) {
    # Bewaar live_logs en .env als die bestaan
    if (Test-Path "$BotDir\.env") { Copy-Item "$BotDir\.env" "$env:TEMP\xauusd_env_backup" -Force }
    if (Test-Path $LogDir) { Copy-Item $LogDir "$env:TEMP\xauusd_logs_backup" -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path (Split-Path $BotDir) | Out-Null
Expand-Archive -Path $ZipPath -DestinationPath (Split-Path $BotDir) -Force
if (-not (Test-Path $BotDir)) {
    # Zip might have extracted to a subfolder
    $extracted = Get-ChildItem (Split-Path $BotDir) -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Rename-Item $extracted.FullName $BotDir
}
# Herstel .env backup
if (Test-Path "$env:TEMP\xauusd_env_backup") { Copy-Item "$env:TEMP\xauusd_env_backup" "$BotDir\.env" -Force }

Log "Bestanden geextraheerd"

# 4. Maak log dir aan
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# 5. Venv aanmaken en dependencies installeren
$venvPython = "$BotDir\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Log "Virtuele omgeving aanmaken..."
    & $python -m venv "$BotDir\.venv"
    Log "Dependencies installeren (kan 2-3 minuten duren)..."
    & "$BotDir\.venv\Scripts\pip.exe" install --upgrade pip --quiet
    & "$BotDir\.venv\Scripts\pip.exe" install -r "$BotDir\requirements.txt" --quiet
    Log "Dependencies geinstalleerd"
} else {
    Log "Virtuele omgeving al aanwezig"
}

# 6. .env aanmaken als niet aanwezig
if (-not (Test-Path "$BotDir\.env")) {
    Log "WAARSCHUWING: .env niet gevonden — standaard aanmaken"
    # .env wordt later geupdated
    @"
AUTONOMOUS_MODE=demo
MT5_LOGIN=1513372223
MT5_PASSWORD=z*Rx58Y9@1L7?8
MT5_SERVER=FTMO-Demo
TELEGRAM_BOT_TOKEN=8757076306:AAELjx_KSypJYS0C_O-u_D8ur-jfgzs4rVM
TELEGRAM_CHAT_ID=5921087860
TELEGRAM_OWNER_USER_ID=5921087860
"@ | Set-Content "$BotDir\.env" -Encoding UTF8
    Log ".env aangemaakt"
}

# 7. Dry-run check
Log "Systeem valideren..."
$dryRun = & $venvPython "$BotDir\scripts\run_live_bot.py" --mode demo --dry-run 2>&1
if ($LASTEXITCODE -ne 0) {
    Log "WAARSCHUWING: Pre-flight had issues:"
    Write-Host $dryRun
} else {
    Log "Pre-flight geslaagd"
}

# 8. Verwijder stale lock
Remove-Item "$LogDir\bot.lock" -ErrorAction SilentlyContinue

# 9. Watchdog als Windows Scheduled Task (auto-start bij reboot)
Log "Watchdog installeren als Windows Scheduled Task..."

# Pas watchdog.ps1 aan voor VPS pad
$watchdogScript = Get-Content "$BotDir\scripts\watchdog.ps1" -Raw
$watchdogScript = $watchdogScript -replace '\$BotDir\s*=\s*"[^"]*"', "`$BotDir = `"$BotDir`""
$watchdogScript = $watchdogScript -replace '\$Mode\s*=\s*"[^"]*"', '`$Mode = "demo"'
Set-Content "$BotDir\scripts\watchdog.ps1" $watchdogScript -Encoding UTF8

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -NonInteractive -File `"$BotDir\scripts\watchdog.ps1`"" `
    -WorkingDirectory $BotDir

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "XAUUSD Trading Bot Watchdog — herstart automatisch na crash" `
    -Force | Out-Null

Log "Watchdog geregistreerd als: $TaskName"

# 10. Start de watchdog (die start de bot automatisch)
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8

# Check of bot gestart is
$botRunning = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine -like "*run_live_bot*"
}

if ($botRunning) {
    $pid_ = ($botRunning | Select-Object -First 1).Id
    Log "=== BOT ACTIEF (PID=$pid_) ==="
    Send-Telegram @"
VPS SETUP VOLTOOID

Bot is gestart op $(hostname) (PID=$pid_)
Mode: DEMO | XAUUSD
Watchdog: actief (auto-herstart bij crash)
Server: $((Invoke-RestMethod 'https://api.ipify.org').Trim())

Bot blijft draaien na verbinding verbreking.
Eerste 2-uurs rapport volgt automatisch.
"@
} else {
    # Bot wordt gestart door watchdog — even wachten
    Log "Watchdog gestart — bot wordt geladen (30 sec)..."
    Start-Sleep -Seconds 25
    $botRunning2 = Get-Process python -ErrorAction SilentlyContinue
    if ($botRunning2) {
        Log "=== BOT ACTIEF ==="
        Send-Telegram "VPS: Bot actief op $(hostname). Watchdog bewaakt 24/7."
    } else {
        Log "Bot nog niet zichtbaar — watchdog bewaakt en start binnen 60s"
        Send-Telegram "VPS setup klaar op $(hostname). Watchdog actief. Bot start over max 60 sec."
    }
}

Log ""
Log "SETUP VOLTOOID"
Log "Logs: Get-Content $LogDir\bot_stdout.log -Wait"
Log "Status: Get-Content $LogDir\heartbeat.json"
Log "Watchdog: Get-ScheduledTask -TaskName '$TaskName'"
