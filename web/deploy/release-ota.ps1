# ============================================================
# release-ota.ps1 - build & publish an OTA web-bundle update (Capgo self-hosted).
#
# Steps: npm run build -> zip dist into <version>.zip (index.html at archive root, as
# Capgo expects) -> write manifest latest.json into server/ota_bundles/.
# The local server serves it at /app/updates (reads the file on every request).
# For PROD: copy the zip + latest.json to server/ota_bundles/ on the VPS (see output).
#
# Run:  powershell -ExecutionPolicy Bypass -File web\deploy\release-ota.ps1 [-Version 1.0.5]
# (ASCII-only on purpose: PowerShell 5.1 reads .ps1 as ANSI, non-ASCII breaks parsing.)
# ============================================================
param([string]$Version = "")
$ErrorActionPreference = 'Stop'

$web    = Split-Path -Parent $PSScriptRoot            # ...\web
$root   = Split-Path -Parent $web                     # repo root
$server = Join-Path $root "server"
$otaDir = Join-Path $server "ota_bundles"

if (-not $Version) { $Version = "1.0." + (Get-Date -Format 'yyMMddHHmm') }  # monotonic

Write-Host "== Building web ==" -ForegroundColor Cyan
Push-Location $web
try { & npm run build } finally { Pop-Location }

New-Item -ItemType Directory -Force $otaDir | Out-Null
$zip = Join-Path $otaDir "$Version.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }

Write-Host "== Packing bundle $Version.zip ==" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $web "dist\*") -DestinationPath $zip
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()

# Manifest WITHOUT checksum by default (a wrong checksum format would block the update).
# sha256 is printed below; add a "checksum" key to latest.json once the format is verified.
$manifestPath = Join-Path $otaDir "latest.json"
$manifest = [ordered]@{ version = $Version; file = "$Version.zip" } | ConvertTo-Json
Set-Content -Path $manifestPath -Value $manifest -Encoding utf8

Write-Host ""
Write-Host "OTA release ready:" -ForegroundColor Green
Write-Host "  version : $Version"
Write-Host "  bundle  : $zip"
Write-Host "  sha256  : $sha"
Write-Host "  manifest: $manifestPath"
Write-Host ""
Write-Host "Local server already serves it at /app/updates (no restart needed)."
Write-Host "For PROD: copy the bundle + latest.json to server/ota_bundles/ on the VPS via scp."
