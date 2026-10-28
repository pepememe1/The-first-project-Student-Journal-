# Копия базы с сервера на этот ПК (27.10.2026). Запускает планировщик Windows: при входе
# и каждые 6 часов, пока ПК включён. Копия зашифрована ключом базы — без ключа это шум.
#
# Ключ и остальные секреты сервера (.env) раз в неделю копируются сюда же под DPAPI:
# расшифровать их может только эта учётка Windows на этом ПК. Без ключа копии базы в аварию
# бесполезны, а открытым текстом секретам на диске не место. Как достать — в шпаргалке.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$Dir = if (Test-Path 'D:\') { 'D:\GradeBookAI-backups' } else { Join-Path $env:USERPROFILE 'GradeBookAI-backups' }
$Keep = 30
New-Item -ItemType Directory -Force $Dir | Out-Null
$Log = Join-Path $Dir 'pull.log'

function Write-Log([string]$message) {
    Add-Content -Path $Log -Value ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $message) -Encoding UTF8
}

function Invoke-Server([string]$command) {
    $out = & ssh -o BatchMode=yes -o ConnectTimeout=20 gb $command
    if ($LASTEXITCODE -ne 0) { throw "сервер не выполнил: $command" }
    return ($out -join "`n").Trim()
}

try {
    $name, $sha, $size = (Invoke-Server 'bash /root/gb-deploy/maintenance/gb_offsite.sh latest') -split '\s+'
    $dst = Join-Path $Dir $name
    if (-not (Test-Path $dst)) {
        $part = "$dst.part"
        & scp -q -o BatchMode=yes -o ConnectTimeout=20 "gb:/root/gb-backups/auto/$name" $part
        if ($LASTEXITCODE -ne 0) { throw "scp не скачал $name" }
        $got = (Get-FileHash $part -Algorithm SHA256).Hash.ToLower()
        if ($got -ne $sha) { Remove-Item $part -Force; throw "хеш $name не совпал — файл удалён" }
        Move-Item $part $dst -Force
        Write-Log "скачана $name ($size байт), хеш сверен"
    }
    Invoke-Server "bash /root/gb-deploy/maintenance/gb_offsite.sh confirm $name $sha" | Out-Null

    $envCopy = Join-Path $Dir 'server-env.dpapi'
    if (-not (Test-Path $envCopy) -or ((Get-Date) - (Get-Item $envCopy).LastWriteTime).TotalDays -ge 7) {
        Add-Type -AssemblyName System.Security
        $raw = [Text.Encoding]::UTF8.GetBytes((Invoke-Server 'cat /root/gb-deploy/server/.env'))
        $sealed = [Security.Cryptography.ProtectedData]::Protect($raw, $null, 'CurrentUser')
        [IO.File]::WriteAllBytes($envCopy, $sealed)
        Write-Log 'обновлена копия секретов сервера (под DPAPI)'
    }

    Get-ChildItem $Dir -Filter 'gradebook_*.db' | Sort-Object Name -Descending |
        Select-Object -Skip $Keep | Remove-Item -Force
} catch {
    Write-Log "ОШИБКА: $($_.Exception.Message)"
    exit 1
}
