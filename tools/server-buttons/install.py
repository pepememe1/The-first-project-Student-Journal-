"""Ставит кнопки сервера на рабочий стол Windows (27.10.2026).

Скрипты и иконки копируются в %LOCALAPPDATA%\\GradeBookAI-ops: ярлыки не должны пропасть,
когда в репозитории переключат ветку. .ps1 пишутся с BOM — без него PowerShell 5.1 читает
кириллицу как ANSI и падает на разборе. Ярлыки создаёт PowerShell через -EncodedCommand:
так русские имена ярлыков доезжают без потерь.

Заодно ставится задача планировщика «GradeBookAI — копия базы» (28.10.2026): при входе в
Windows и каждые 6 часов, пока ПК включён, offsite_pull.ps1 забирает ночную копию базы с
сервера. Запуск через wscript и .vbs — чтобы окно PowerShell не мелькало поверх работы.

Запуск: py -3.11 -X utf8 tools/server-buttons/install.py
"""
import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = Path(os.environ["LOCALAPPDATA"]) / "GradeBookAI-ops"
WT = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WindowsApps" / "wt.exe"

#(имя ярлыка, иконка, что запускать, аргументы)
SHORTCUTS = (
    ("Жесткий Рубильник", "hard_switch", "powershell.exe", "hard_switch.ps1"),
    ("Рестарт сервера", "restart", "powershell.exe", "restart.ps1"),
    ("Откат бэкап", "rollback", "powershell.exe", "rollback.ps1"),
    ("Консоль сервера", "console", None, None),
    ("Шпаргалка по серверу", "guide", None, "guide.html"),
)


TASK = "GradeBookAI — копия базы"


def _powershell(script: str) -> subprocess.CompletedProcess:
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", enc],
                          capture_output=True, text=True, encoding="cp866", errors="replace")


def register_offsite_task() -> int:
    """Задача текущего пользователя, без прав администратора и без пароля."""
    vbs = TARGET / "offsite_pull.vbs"
    vbs.write_text('CreateObject("WScript.Shell").Run "powershell.exe -NoProfile '
                   '-ExecutionPolicy Bypass -File ""%s""", 0, False\r\n'
                   % (TARGET / "offsite_pull.ps1"), encoding="utf-16")
    script = "\n".join([
        "$a = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '\"%s\"'" % vbs,
        #При входе — с задержкой: сеть и VPN поднимаются не сразу.
        "$t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME",
        "$t1.Delay = 'PT3M'",
        "$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(10) "
        "-RepetitionInterval (New-TimeSpan -Hours 6)",
        #Пропущенный запуск (ПК спал) выполняется при первой возможности.
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) "
        "-MultipleInstances IgnoreNew",
        "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive "
        "-RunLevel Limited",
        "Register-ScheduledTask -TaskName '%s' -Action $a -Trigger $t1,$t2 -Settings $s "
        "-Principal $p -Description 'Копия базы GradeBookAI с сервера на этот ПК "
        "(tools/server-buttons/offsite_pull.ps1)' -Force | Out-Null" % TASK,
        "Write-Output ('задача: ' + (Get-ScheduledTask -TaskName '%s').State)" % TASK,
    ])
    out = _powershell(script)
    print(out.stdout.strip() or out.stderr.strip())
    return out.returncode


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for ps1 in HERE.glob("*.ps1"):
        text = ps1.read_text(encoding="utf-8")
        (TARGET / ps1.name).write_text(text, encoding="utf-8-sig", newline="\r\n")
    shutil.copy2(HERE / "guide.html", TARGET / "guide.html")
    subprocess.run([sys.executable, str(HERE / "make_icons.py"), str(TARGET)], check=True)
    for png in TARGET.glob("*.png"):
        png.unlink()

    lines = ["$sh = New-Object -ComObject WScript.Shell",
             "$desk = [Environment]::GetFolderPath('Desktop')"]
    for name, icon, exe, arg in SHORTCUTS:
        if name == "Консоль сервера":
            if WT.exists():
                exe, args = str(WT), "ssh gb"
            else:
                exe, args = "powershell.exe", "-NoExit -Command ssh gb"
        elif exe is None:
            exe, args = str(TARGET / arg), ""
        else:
            args = '-NoProfile -ExecutionPolicy Bypass -File "%s"' % (TARGET / arg)
        lines += [
            "$l = $sh.CreateShortcut((Join-Path $desk '%s.lnk'))" % name,
            "$l.TargetPath = '%s'" % exe,
            "$l.Arguments = '%s'" % args.replace("'", "''"),
            "$l.WorkingDirectory = '%s'" % TARGET,
            "$l.IconLocation = '%s,0'" % (TARGET / ("%s.ico" % icon)),
            "$l.Description = 'GradeBookAI: %s'" % name,
            "$l.Save()",
        ]
    lines.append("Write-Output ('ярлыки на ' + $desk)")
    out = _powershell("\n".join(lines))
    print(out.stdout.strip() or out.stderr.strip())
    print("скрипты и иконки:", TARGET)
    return out.returncode or register_offsite_task()


if __name__ == "__main__":
    sys.exit(main())
