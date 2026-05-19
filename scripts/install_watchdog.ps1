# ============================================================
#  Installeert de watchdog als Windows Scheduled Task
#  Uitvoeren als Administrator op de VPS:
#    powershell -ExecutionPolicy Bypass -File scripts\install_watchdog.ps1
# ============================================================

$BotDir     = "C:\TradingBot"
$ScriptPath = "$BotDir\scripts\watchdog.ps1"
$TaskName   = "XAUUSD_Watchdog"

# Verwijder oude taak als die bestaat
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`"" `
    -WorkingDirectory $BotDir

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 10 `
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
    -Description "Herstart de XAUUSD trading bot als die crasht of vastloopt" `
    -Force

Write-Host ""
Write-Host "Watchdog geinstalleerd als taak: $TaskName"
Write-Host "Direct starten:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""

# Meteen starten
Start-ScheduledTask -TaskName $TaskName
Write-Host "Watchdog draait nu op de achtergrond."
