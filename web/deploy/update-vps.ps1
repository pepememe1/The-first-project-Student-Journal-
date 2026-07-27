# update-vps.ps1 — обновить сайт И серверный код на VPS одной командой.
#
# ЗАПУСКАТЬ НА СВОЁМ КОМПЬЮТЕРЕ (PowerShell в VS Code), НЕ на VPS. Требует Git Bash
# (обычно уже стоит вместе с Git for Windows) — вызывает bash-скрипты deploy/*.sh.
#
# ⚠️ Windows по умолчанию ЗАПРЕЩАЕТ запуск .ps1 (execution policy = Restricted) —
# при обычном запуске файла будет "выполнение сценариев отключено в этой системе",
# это НЕ ошибка в самом скрипте. Два варианта:
#   powershell -ExecutionPolicy Bypass -File web\deploy\update-vps.ps1
#   ИЛИ проще — вызвать сами bash-скрипты напрямую из Git Bash, без .ps1 вообще:
#     bash deploy/deploy-web.sh && bash deploy/deploy-server.sh
#
# ⚠️ ИСПРАВЛЕНО (была причина «код есть локально, а сервер всё равно 404/405»):
#   1) Раньше скрипт считал web/ и server/ ДВУМЯ отдельными репозиториями рядом
#      друг с другом (наследие до-монорепо структуры) — путь `$ServerRepo` вёл в
#      несуществующую папку, и на самом деле НИКОГДА не находил server/app/routers/web.py
#      в актуальном виде (либо падал, либо тянул не то).
#   2) Даже когда путь совпадал, скрипт заливал ТОЛЬКО ОДИН файл — routers/web.py.
#      Любая правка в ДРУГОМ файле (routers/parent.py, routers/messenger.py,
#      models.py — как в этой сессии) на сервер никогда не попадала: 404/405 на
#      новых эндпоинтах при полностью готовом и протестированном локальном коде.
# Теперь скрипт — тонкая обёртка над deploy/deploy-web.sh (весь web/dist, одним
# архивом) и deploy/deploy-server.sh (ВЕСЬ server/app/, тем же надёжным способом,
# не трогая server/.env и БД) — оба уже держат путь монорепо и полную папку, а не
# один файл.
$ErrorActionPreference = "Stop"
# Split-Path/Join-Path — только нативные Windows-пути (обратный слэш), без ручной
# склейки строк со слэшем: смешение \ и / в одном литерале — частый источник
# «то работает, то нет» на разных версиях Git Bash/MSYS2.
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent   # корень монорепо
$DeployWebSh    = Join-Path $RepoRoot "deploy\deploy-web.sh"
$DeployServerSh = Join-Path $RepoRoot "deploy\deploy-server.sh"

$Bash = (Get-Command bash -ErrorAction SilentlyContinue)
if (-not $Bash) {
  throw "bash не найден в PATH — нужен Git Bash (ставится вместе с Git for Windows)."
}

Write-Host "== Деплой сайта (web/dist) ==" -ForegroundColor Cyan
& bash $DeployWebSh
if ($LASTEXITCODE -ne 0) { throw "deploy-web.sh завершился с ошибкой (код $LASTEXITCODE)" }

Write-Host "== Деплой сервера (server/app) ==" -ForegroundColor Cyan
& bash $DeployServerSh
if ($LASTEXITCODE -ne 0) { throw "deploy-server.sh завершился с ошибкой (код $LASTEXITCODE)" }

Write-Host "Готово. Обновлено на https://esstu-gradebook.ru" -ForegroundColor Green
