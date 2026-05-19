# ============================================================
#  XAUUSD Bot Watchdog — houdt de bot 24/7 online
#  Controleert elke 60 seconden:
#    1. Draait het Python process nog?
#    2. Is de heartbeat recent (< 3 minuten oud)?
#  Bij fout: bot wordt gestopt en herstart.
#
#  Installeren als Windows taak:
#    powershell -ExecutionPolicy Bypass -File scripts\install_watchdog.ps1
# ============================================================

$BotDir      = "C:\TradingBot\XAUUSD"
$BotScript   = "scripts\run_live_bot.py"
$HeartbeatF  = "$BotDir\live_logs\heartbeat.json"
$LogFile     = "$BotDir\live_logs\watchdog.log"
$LockFile    = "$BotDir\live_logs\bot.lock"
$Mode        = "demo"   # verander naar "live" als je live gaat
$VenvPython  = "$BotDir\.venv\Scripts\python.exe"
$MaxHeartbeatAgeSeconds = 180  # 3 minuten zonder heartbeat = bot vastgelopen

function Write-Log {
    param([string]$Message)
    $ts = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
    $line = "$ts  $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-BotProcess {
    Get-Process -Name "python" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*run_live_bot*" -or (
            (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine -like "*run_live_bot*"
        )}
}

function Stop-Bot {
    $procs = Get-BotProcess
    foreach ($p in $procs) {
        Write-Log "Stoppen bot process PID=$($p.Id)"
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -Path $LockFile -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

function Start-Bot {
    Write-Log "Bot starten: mode=$Mode"
    $python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
    Start-Process -FilePath $python `
        -ArgumentList "$BotScript --mode $Mode --log-level INFO" `
        -WorkingDirectory $BotDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput "$BotDir\live_logs\bot_stdout.log" `
        -RedirectStandardError  "$BotDir\live_logs\bot_stderr.log"
    Start-Sleep -Seconds 5
    Write-Log "Bot gestart"
}

function Test-HeartbeatFresh {
    if (-not (Test-Path $HeartbeatF)) { return $false }
    $lastWrite = (Get-Item $HeartbeatF).LastWriteTime
    $ageSeconds = ((Get-Date) - $lastWrite).TotalSeconds
    return $ageSeconds -lt $MaxHeartbeatAgeSeconds
}

# ── Hoofdlus ─────────────────────────────────────────────────────────────────
Write-Log "=== Watchdog gestart (interval=60s, heartbeat_max=${MaxHeartbeatAgeSeconds}s) ==="

while ($true) {
    $botProc = Get-BotProcess

    if (-not $botProc) {
        Write-Log "WAARSCHUWING: Bot process niet gevonden — herstart..."
        Stop-Bot
        Start-Bot
    }
    elseif (-not (Test-HeartbeatFresh)) {
        $age = if (Test-Path $HeartbeatF) {
            [int]((Get-Date) - (Get-Item $HeartbeatF).LastWriteTime).TotalSeconds
        } else { 9999 }
        Write-Log "WAARSCHUWING: Heartbeat $age seconden oud (max $MaxHeartbeatAgeSeconds) — bot vastgelopen, herstart..."
        Stop-Bot
        Start-Bot
    }
    else {
        $pid_ = ($botProc | Select-Object -First 1).Id
        Write-Log "OK — bot actief (PID=$pid_), heartbeat vers"
    }

    Start-Sleep -Seconds 60
}
