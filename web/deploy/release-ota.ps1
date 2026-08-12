# ============================================================
# release-ota.ps1 - build & publish an OTA web-bundle update (Capgo self-hosted).
#
# Steps: npm run build -> zip dist into <version>.zip (index.html at archive root, as
# Capgo expects) -> write manifest latest.json into server/ota_bundles/ -> optionally
# upload both to the VPS. The server serves it at /app/updates (file is read on every
# request, so no restart is needed).
#
# Run:  powershell -ExecutionPolicy Bypass -File web\deploy\release-ota.ps1 [-Deploy]
#       powershell -ExecutionPolicy Bypass -File web\deploy\release-ota.ps1 -Version 1.260731.1830
# (ASCII-only on purpose: PowerShell 5.1 reads .ps1 as ANSI, non-ASCII breaks parsing.)
#
# ---- VERSION SCHEME: 1.<yyMMdd>.<HHmm> -- DO NOT go back to "1.0.<yyMMddHHmm>" ----
# The old scheme produced e.g. 1.0.2607292034, whose last part (2,607,292,034) does not
# fit into a signed 32-bit integer (max 2,147,483,647). Capgo parses bundle versions
# with a semver comparator; an out-of-range component is undefined behaviour we do not
# control, and every bundle we ever shipped had it. Splitting date and time keeps both
# parts small (260731 and 1830) and still strictly increasing over time.
#
# ---- CHECKSUM IS ALWAYS WRITTEN ----
# It used to be omitted "in case the format is wrong". The format is verified: Capgo's
# CryptoCipher.calcChecksum uses SHA-256 and compares the lowercase hex string, which is
# exactly what Get-FileHash produces. Without a checksum a truncated download would be
# installed as-is and brick the app until the next release.
# ============================================================
param(
    [string]$Version = "",
    [switch]$Deploy,
    [string]$VpsHost = "root@194.226.120.74",
    [string]$SshKey  = "$env:USERPROFILE\.ssh\gb_vps_ed25519"
)
$ErrorActionPreference = 'Stop'

$web    = Split-Path -Parent $PSScriptRoot            # ...\web
$root   = Split-Path -Parent $web                     # repo root
$server = Join-Path $root "server"
$otaDir = Join-Path $server "ota_bundles"

if (-not $Version) {
    $Version = "1." + (Get-Date -Format 'yyMMdd') + "." + (Get-Date -Format 'HHmm')
}

Write-Host "== Building web ==" -ForegroundColor Cyan
Push-Location $web
try { & npm run build; if ($LASTEXITCODE -ne 0) { throw "npm run build failed" } }
finally { Pop-Location }

New-Item -ItemType Directory -Force $otaDir | Out-Null
$zip = Join-Path $otaDir "$Version.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }

Write-Host "== Packing bundle $Version.zip ==" -ForegroundColor Cyan
# ---- DO NOT USE Compress-Archive HERE. THIS WAS THE BUG. -----------------------------
# Compress-Archive on Windows PowerShell 5.1 stores entry names with BACKSLASHES
# ("assets\index-abc.js"). The ZIP spec (APPNOTE 4.4.17) requires forward slashes, and
# Java/Android read the name literally: instead of a folder "assets" the phone gets ONE
# file whose NAME contains a backslash. index.html then asks for /assets/index-abc.js,
# which no longer exists -> the bundle fails to finish installing. On the device this
# showed up as "finish_download_fail", i.e. it looked like a broken download.
# Cost of that one cmdlet: OTA updates never applied on any phone for a month, while the
# server logs showed every bundle served with HTTP 200.
# ZipFile::CreateFromDirectory was tried next and does THE SAME on .NET Framework here
# (the guard below caught it immediately). PowerShell has no built-in packer that writes
# spec-compliant names, so packing is done by tools/pack_ota_bundle.py - see its docstring.
Add-Type -AssemblyName System.IO.Compression.FileSystem
& python -X utf8 (Join-Path $root "tools\pack_ota_bundle.py") (Join-Path $web "dist") $zip
if ($LASTEXITCODE -ne 0) { throw "packing the bundle failed" }
$sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()

# Sanity checks. Both failures below are silent on the phone and expensive to diagnose
# afterwards, so the release stops here rather than shipping a bundle that cannot install:
#   1. Capgo needs index.html at the ARCHIVE ROOT. A nested folder yields a bundle that
#      installs and then shows a blank screen, which rolls back silently.
#   2. No backslashes in entry names (see the note above) - the guard exists because the
#      packer was wrong for a month and nothing anywhere complained.
$archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
try {
    $hasIndex = $archive.Entries | Where-Object { $_.FullName -eq 'index.html' }
    if (-not $hasIndex) { throw "index.html is not at the archive root - Capgo would reject this bundle" }
    $bad = @($archive.Entries | Where-Object { $_.FullName -like '*\*' })
    if ($bad.Count -gt 0) {
        throw "$($bad.Count) entries use backslashes (e.g. '$($bad[0].FullName)') - Android would create files instead of folders"
    }
} finally { $archive.Dispose() }

$manifestPath = Join-Path $otaDir "latest.json"
$manifest = [ordered]@{ version = $Version; file = "$Version.zip"; checksum = $sha } | ConvertTo-Json
Set-Content -Path $manifestPath -Value $manifest -Encoding utf8

Write-Host ""
Write-Host "OTA release ready:" -ForegroundColor Green
Write-Host "  version : $Version"
Write-Host "  bundle  : $zip"
Write-Host "  sha256  : $sha"
Write-Host "  manifest: $manifestPath"

if ($Deploy) {
    Write-Host ""
    Write-Host "== Uploading to $VpsHost ==" -ForegroundColor Cyan
    $remote = "/root/gb-deploy/server/ota_bundles"
    & scp -i $SshKey -o BatchMode=yes $zip "${VpsHost}:$remote/"
    if ($LASTEXITCODE -ne 0) { throw "scp of the bundle failed" }
    & scp -i $SshKey -o BatchMode=yes $manifestPath "${VpsHost}:$remote/"
    if ($LASTEXITCODE -ne 0) { throw "scp of the manifest failed" }

    # Verify what the site actually serves. Uploading and assuming is how a release
    # gets announced as done while phones keep getting the previous bundle.
    $live = Invoke-RestMethod -Uri "https://esstu-gradebook.ru/app/updates" -Method Post `
        -ContentType "application/json" -Body '{"platform":"android"}'
    Write-Host ""
    if ($live.version -eq $Version) {
        Write-Host "LIVE: /app/updates now serves $($live.version)" -ForegroundColor Green
    } else {
        Write-Host "WARNING: /app/updates serves $($live.version), expected $Version" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "Not deployed. Re-run with -Deploy to upload to the VPS."
}
