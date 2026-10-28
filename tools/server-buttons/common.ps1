# Общее для кнопок сервера на рабочем столе (27.10.2026). Подключается из каждой кнопки.
# Все действия — по ssh на алиас `gb` (ключ ~/.ssh/gb_vps_ed25519, см. шпаргалку).
# Вывод сервера идёт в UTF-8: без смены кодировки вывода кириллица превращается в кракозябры.
# Кодировку ВВОДА не трогаем: с 65001 консоль PowerShell 5.1 теряет русские буквы в Read-Host.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
$Site = 'https://esstu-gradebook.ru'

function Show-Title([string]$title, [string]$hint) {
    $Host.UI.RawUI.WindowTitle = "GradeBookAI — $title"
    Write-Host ''
    Write-Host "  $title" -ForegroundColor Cyan
    if ($hint) { Write-Host "  $hint" -ForegroundColor DarkGray }
    Write-Host ''
}

function Ask-Yes([string]$question) {
    # «да» в английской раскладке — «lf»: кнопка не должна ломаться из-за раскладки.
    $a = (Read-Host "$question  (да / нет)").Trim().ToLower()
    return @('да', 'д', 'lf', 'l', 'yes', 'y') -contains $a
}

function Invoke-Gb([string]$command) {
    # Вывод сервера сразу на экран; возвращает код выхода команды на сервере.
    # Out-Host обязателен: без него вывод ssh стал бы результатом функции вместе с кодом.
    & ssh -o ConnectTimeout=15 gb $command | Out-Host
    return $LASTEXITCODE
}

function Get-Gb([string]$command) {
    # То же, но вывод возвращается строкой (для «что сейчас»).
    $out = & ssh -o ConnectTimeout=15 gb $command
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($out -join "`n").Trim()
}

function Get-SiteCode {
    try {
        $r = Invoke-WebRequest -Uri "$Site/health" -UseBasicParsing -TimeoutSec 15
        return [int]$r.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}

function Show-Site {
    $code = Get-SiteCode
    switch ($code) {
        200     { Write-Host "  Сайт снаружи: работает (200)" -ForegroundColor Green }
        503     { Write-Host "  Сайт снаружи: страница технических работ (503)" -ForegroundColor Yellow }
        0       { Write-Host "  Сайт снаружи: не отвечает" -ForegroundColor Red }
        default { Write-Host "  Сайт снаружи: код $code" -ForegroundColor Red }
    }
}

function Stop-NoServer {
    Write-Host ''
    Write-Host '  Нет связи с сервером по ssh.' -ForegroundColor Red
    Write-Host '  Проверь интернет и VPN. Если ssh не пускает совсем — консоль VNC в панели reg.ru' -ForegroundColor DarkGray
    Write-Host '  (пользователь gbadmin, пароль — в менеджере паролей), подробно — в шпаргалке.' -ForegroundColor DarkGray
    Close-Window
}

function Close-Window {
    Write-Host ''
    Read-Host '  Нажми Enter, чтобы закрыть окно' | Out-Null
    exit
}
