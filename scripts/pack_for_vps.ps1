# ============================================================
#  XAUUSD Bot — Inpakken voor VPS upload
#  Voer dit uit op JOUW PC (niet de VPS)
# ============================================================

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$TempDir     = "$env:TEMP\XAUUSD_pack"
$ZipDest     = "$env:USERPROFILE\Downloads\XAUUSD_VPS.zip"

Write-Host "Project inpakken: $ProjectRoot" -ForegroundColor Cyan
Write-Host "Uitvoer: $ZipDest" -ForegroundColor Cyan

# Opruimen van vorige runs
if (Test-Path $TempDir)  { Remove-Item $TempDir -Recurse -Force }
if (Test-Path $ZipDest)  { Remove-Item $ZipDest -Force }

# Kopieer bestanden naar temp map, sla grote/onnodige mappen over
Write-Host "Bestanden kopieren (kan even duren)..." -ForegroundColor Yellow
robocopy $ProjectRoot $TempDir /E /NP /NJH /NJS `
    /XD ".venv" "node_modules" "__pycache__" ".git" `
         "exports" "live_logs" "logs" "datasets" `
         "artifacts" ".pytest_cache" ".mypy_cache" | Out-Null

# Zip de temp map
Write-Host "Inpakken als zip..." -ForegroundColor Yellow
Compress-Archive -Path "$TempDir\*" -DestinationPath $ZipDest -CompressionLevel Optimal

# Opruimen
Remove-Item $TempDir -Recurse -Force

$sizeMB = [math]::Round((Get-Item $ZipDest).Length / 1MB, 1)
Write-Host "`nKlaar! Zip aangemaakt: $ZipDest ($sizeMB MB)" -ForegroundColor Green
Write-Host @"

Volgende stappen:
  1. Kopieer XAUUSD_VPS.zip van je bureaublad naar je VPS (via RDP copy-paste)
  2. Op de VPS: pak uit naar C:\bots\XAUUSD
  3. Op de VPS, open PowerShell als Administrator en run:
       PowerShell -ExecutionPolicy Bypass -File C:\bots\XAUUSD\scripts\vps_deploy.ps1
"@
