# update-vps.ps1 — обновить сайт И серверный код на VPS одной командой.
#
# ЗАПУСКАТЬ НА СВОЁМ КОМПЬЮТЕРЕ (локальный PowerShell в VS Code), НЕ на VPS.
# Скрипт: (1) собирает сайт, (2) заливает сборку и обновлённый серверный код на VPS,
# (3) перезапускает сервер и Caddy. Спросит пароль root от VPS несколько раз — это норм.
#
# Что НЕ трогаем на VPS: .env (JWT-секрет, HOST_DEVICE_ID), базу данных — только код.
param(
  [string]$VpsIp = "194.226.120.74",
  [string]$RemoteDir = "/root/gb-deploy"
)
$ErrorActionPreference = "Stop"
$WebDir = Split-Path $PSScriptRoot -Parent                  # корень веб-репозитория
# Десктоп-репозиторий с серверным кодом лежит рядом (папка над GradeBookAI-Web-Edition).
$ServerRepo = Join-Path (Split-Path $WebDir -Parent) "The-first-project-Student-Journal-"
$ServerWeb  = Join-Path $ServerRepo "server\app\routers\web.py"

if (-not (Test-Path $ServerWeb)) { throw "Не найден серверный web.py: $ServerWeb" }

Write-Host "== [1/4] Сборка сайта ==" -ForegroundColor Cyan
Push-Location $WebDir
npm run build
Pop-Location

Write-Host "== [2/4] Заливка сайта (dist) — введи пароль root ==" -ForegroundColor Cyan
ssh "root@$VpsIp" "rm -rf $RemoteDir/webdist"
scp -r "$WebDir\dist" "root@${VpsIp}:$RemoteDir/webdist"

Write-Host "== [3/4] Заливка серверного web.py — введи пароль root ==" -ForegroundColor Cyan
scp "$ServerWeb" "root@${VpsIp}:$RemoteDir/server/app/routers/web.py"

Write-Host "== [4/4] Перезапуск сервера и Caddy — введи пароль root ==" -ForegroundColor Cyan
ssh "root@$VpsIp" "systemctl restart gradebook caddy"

Write-Host "Готово. Обновлено на https://esstu-gradebook.ru" -ForegroundColor Green
