# Кнопка «Откат бэкап»: вернуть прежнюю выкладку кода или базу из ночной копии.
. "$PSScriptRoot\common.ps1"
Show-Title 'ОТКАТ' 'Когда после выкладки всё сломалось — или пропали данные.'

Write-Host '  1 — откатить ВЫКЛАДКУ: сервер и сайт вернутся к прошлой версии.'
Write-Host '      Данные не трогаются. Запустишь ещё раз — вернётся новая версия.'
Write-Host '  2 — вернуть БАЗУ из ночной копии (снимок каждую ночь в 00:00 по колледжу).'
Write-Host '      Всё, что внесли ПОСЛЕ копии, из журнала пропадёт. Нынешняя база сохранится,'
Write-Host '      и её можно вернуть этой же кнопкой (в списке она будет «база до прошлого отката»).'
Write-Host '  0 — ничего не делать'
Write-Host ''
$choice = (Read-Host '  Что делаем').Trim()

if ($choice -eq '1') {
    if (-not (Ask-Yes '  Откатить выкладку к прошлой версии?')) { Close-Window }
    Write-Host ''
    $rc = Invoke-Gb 'bash /root/gb-deploy/maintenance/gb_restore.sh code'
    if ($rc -eq 255) { Stop-NoServer }
} elseif ($choice -eq '2') {
    Write-Host ''
    Write-Host '  Копии базы (время колледжа, новые сверху):' -ForegroundColor Cyan
    $rc = Invoke-Gb 'bash /root/gb-deploy/maintenance/gb_restore.sh list'
    if ($rc -eq 255) { Stop-NoServer }
    Write-Host ''
    $n = (Read-Host '  Номер копии (Enter — отмена)').Trim()
    if ($n -notmatch '^\d+$') { Close-Window }
    Write-Host ''
    $rc = Invoke-Gb "bash /root/gb-deploy/maintenance/gb_restore.sh db $n --dry"
    if ($rc -ne 0) { Close-Window }
    Write-Host ''
    Write-Host '  На минуту сайт закроется страницей работ, потом откроется уже с этой копией.' -ForegroundColor Yellow
    if (-not (Ask-Yes "  Точно вернуть базу к копии №$n?")) { Close-Window }
    Write-Host ''
    $rc = Invoke-Gb "bash /root/gb-deploy/maintenance/gb_restore.sh db $n"
} else {
    Close-Window
}

Write-Host ''
if ($rc -eq 0) { Write-Host '  Готово.' -ForegroundColor Green }
else { Write-Host '  Не получилось — смотри строки выше. Прежнее состояние скрипт вернул сам.' -ForegroundColor Red }
Show-Site
Close-Window
