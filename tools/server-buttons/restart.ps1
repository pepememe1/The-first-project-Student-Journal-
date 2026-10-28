# Кнопка «Рестарт сервера»: перезапуск журнала, Caddy или всей машины с проверкой.
. "$PSScriptRoot\common.ps1"
Show-Title 'РЕСТАРТ СЕРВЕРА' 'Помогает, когда сайт завис или отвечает ошибками.'

Show-Site
Write-Host ''
Write-Host '  1 — перезапустить журнал (5–10 секунд без сайта; обычно этого хватает)'
Write-Host '  2 — журнал и Caddy (если сайт снаружи не открывается, а журнал жив)'
Write-Host '  3 — перезагрузить всю машину (1–2 минуты без сайта; когда не помогло остальное)'
Write-Host '  0 — ничего не делать'
Write-Host ''
$choice = (Read-Host '  Что делаем').Trim()

switch ($choice) {
    '1' { $mode = 'app' }
    '2' { $mode = 'all' }
    '3' {
        if (-not (Ask-Yes '  Точно перезагрузить ВСЮ машину?')) { Close-Window }
        $mode = 'reboot'
    }
    default { Close-Window }
}

Write-Host ''
$rc = Invoke-Gb "bash /root/gb-deploy/maintenance/gb_restart.sh $mode"
if ($rc -eq 255) { Stop-NoServer }

if ($mode -eq 'reboot') {
    Write-Host '  Жду, пока машина вернётся (до 3 минут)…' -ForegroundColor DarkGray
    Start-Sleep -Seconds 20
    for ($i = 0; $i -lt 16; $i++) {
        if ((Get-SiteCode) -eq 200) { break }
        Start-Sleep -Seconds 10
    }
}

Write-Host ''
if ($rc -eq 0) { Write-Host '  Готово.' -ForegroundColor Green }
else { Write-Host '  Что-то пошло не так — смотри строки выше. Можно «Откат бэкап» → откат выкладки.' -ForegroundColor Red }
Show-Site
Close-Window
