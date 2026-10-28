# Кнопка «Жесткий Рубильник»: весь сайт и API показывают страницу технических работ.
. "$PSScriptRoot\common.ps1"
Show-Title 'ЖЁСТКИЙ РУБИЛЬНИК' 'Закрывает ВЕСЬ сайт, API и админку страницей «Вектор чинит журнал».'

Write-Host '  Узнаю, что сейчас…' -ForegroundColor DarkGray
$state = Get-Gb 'bash /root/gb-deploy/maintenance/gb_maintenance.sh status'
if ($null -eq $state) { Stop-NoServer }

if ($state -like 'включён*') {
    Write-Host "  Сейчас: ВКЛЮЧЁН ($state)" -ForegroundColor Yellow
    Write-Host ''
    if (Ask-Yes '  Выключить рубильник и открыть сайт людям?') {
        Invoke-Gb 'bash /root/gb-deploy/maintenance/gb_maintenance.sh off' | Out-Null
        Start-Sleep -Seconds 2
    }
} else {
    Write-Host '  Сейчас: выключен, сайт работает.' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Обычно хватает МЯГКОГО рубильника: админка → «Сервер» → «Технические работы».' -ForegroundColor DarkGray
    Write-Host '  При нём админка остаётся у тебя. Жёсткий нужен, когда сам журнал сломан или его меняют.' -ForegroundColor DarkGray
    Write-Host ''
    if (Ask-Yes '  Включить ЖЁСТКИЙ рубильник?') {
        Invoke-Gb 'bash /root/gb-deploy/maintenance/gb_maintenance.sh on' | Out-Null
        Start-Sleep -Seconds 2
    }
}

Write-Host ''
Write-Host "  Итог: $(Get-Gb 'bash /root/gb-deploy/maintenance/gb_maintenance.sh status')"
Show-Site
Close-Window
