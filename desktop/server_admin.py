"""
server_admin.py — управление боевым сервером ИЗ ПРОГРАММЫ (раздел «Сервер», десктоп).

━━ ГЛАВНОЕ ПРО ГРАНИЦУ ━━
Этот модуль подключается ТОЛЬКО к локальному серверу программы (127.0.0.1, см.
`desktop/local_api.py`). На боевой машине его нет физически — там работает
`server/app/routers/serverinfo.py`, который умеет исключительно СМОТРЕТЬ.

Разделение проходит по наличию кода, а не по проверке роли, и это не перестраховка:
здесь есть выполнение произвольных команд на сервере. Будь этот роутер подключён на
бою, любая дыра в веб-админке означала бы оболочку на машине с персональными данными
всего колледжа. Роль можно обойти; отсутствующий код — нельзя.

━━ ПОЧЕМУ СИСТЕМНЫЙ ssh, А НЕ paramiko ━━
1. Ноль новых зависимостей — .exe и так собирали до 49 МБ не для того, чтобы вернуть
   туда крипто-стек ради одной вкладки.
2. Приватный ключ не проходит через наш код ВООБЩЕ. Мы не читаем его, не храним и не
   передаём — этим занимается OpenSSH, который есть в Windows 10/11 из коробки.
3. Уже настроенные `~/.ssh/config` и агент работают сами: команда `ssh gb` из README
   продолжает означать ровно то же самое.

━━ ВХОД ПО ПАРОЛЮ ━━
Поддержан, хотя ключ надёжнее. Причина не в удобстве: НОВАЯ машина (например, компьютер
ВСГУТУ) приезжает с парольным входом, и без него на неё нечем зайти, чтобы положить
туда свой ключ. Запрет пароля означал бы, что перенос сервера невозможен в принципе.

Что при этом сделано, чтобы пароль не стал постоянной дырой:
  • он шифруется DPAPI (`security.os_protect`) — тот же приём, что у «Входа по Windows»
    (§4.7 CLAUDE.md), файл настроек на другом компьютере бесполезен;
  • он НИКОГДА не возвращается странице: наружу уходит только признак `has_password`;
  • рядом есть кнопка «положить ключ на сервер» (`install_key`) — один раз по паролю, и
    дальше вход уже по ключу, а пароль можно стереть.
Системный `ssh` пароль ввести не умеет (BatchMode), поэтому парольные соединения идут
через `paramiko` — он импортируется ЛЕНИВО и только на этом пути.

━━ ЧТО ХРАНИМ ━━
Адрес, пользователя, порт, путь к ключу и (если задан) зашифрованный пароль — в
локальных настройках программы (`data_store.local_set`, не уезжает на сервер).
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid

import log

_LOG = log.get("server_admin")

#Ключ локальной настройки со списком серверов.
_KEY = "remote_servers"

#Сколько ждём ответа. Команды администратора бывают долгими (перенос базы), но
#бесконечное ожидание вешает вкладку — поэтому предел есть, просто щедрый.
_TIMEOUT_QUICK = 25
_TIMEOUT_LONG = 900

#Опции ssh, одинаковые для всех вызовов.
#  BatchMode — НИКОГДА не спрашивать пароль/фразу интерактивно: спросить некому,
#             процесс без консоли просто повис бы навсегда.
#  StrictHostKeyChecking=accept-new — первый ключ хоста принимаем, ПОДМЕНУ отвергаем.
#             Полное `no` приняло бы и подменённый — это и есть та самая атака
#             «человек посередине», от которой ключ хоста и защищает.
_SSH_OPTS = ["-o", "BatchMode=yes",
             "-o", "StrictHostKeyChecking=accept-new",
             "-o", "ConnectTimeout=12"]


# ── Хранилище списка серверов ────────────────────────────────────────────────────────
def _load() -> list:
    try:
        from data import data_store
        raw = data_store.local_get(_KEY, "[]")
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        return items if isinstance(items, list) else []
    except Exception as e:      # noqa: BLE001
        _LOG.warning(f"[server-admin] список серверов не прочитан: {e}")
        return []


def _save(items: list) -> bool:
    try:
        from data import data_store
        return bool(data_store.local_set(_KEY, json.dumps(items, ensure_ascii=False)))
    except Exception as e:      # noqa: BLE001
        _LOG.warning(f"[server-admin] список серверов не сохранён: {e}")
        return False


def _find(server_id: str) -> dict:
    for s in _load():
        if s.get("id") == server_id:
            return s
    return {}


def ensure_seeded() -> list:
    """Завести боевой сервер в списке САМИМ, если список пуст.

    Иначе получалось нелепо: раздел уже показывает состояние боевой машины (диск,
    память, база — всё про неё), а рядом висит «сервер ещё не добавлен» и предлагает
    добавить то, что человек и так видит. Разница между этими двумя вещами
    (просмотр через API против управления по SSH) очевидна нам и совершенно не очевидна
    тому, кто открыл вкладку.

    Заводим ровно тот адрес, на который программа и так синхронизируется, и ключ,
    которым команда и так ходит. Ничего не подключаем и никуда не лезем — просто
    заполняем форму за человека; если не подойдёт, он поправит адрес или добавит пароль."""
    items = _load()
    if items:
        return items
    host = suggested_host()
    if not host:
        return items
    row = {"id": uuid.uuid4().hex[:8], "name": "Боевой сервер", "host": host,
           "user": "root", "port": "22", "key": _default_key(), "pw": "", "role": "prod"}
    _save([row])
    _LOG.info(f"[server-admin] список пуст — завёл боевой сервер {host}")
    return [row]


def _default_key() -> str:
    """Ключ по умолчанию — тот, которым команда уже ходит на боевой VPS."""
    path = os.path.join(os.path.expanduser("~"), ".ssh", "gb_vps_ed25519")
    return path if os.path.isfile(path) else ""


def suggested_host() -> str:
    """Адрес боевого сервера из настроек программы — чтобы форму не заполнять руками.

    Берём тот же адрес, на который программа и так синхронизируется: это ровно та
    машина, состояние которой человек хочет увидеть."""
    try:
        from data import app_settings
        from urllib.parse import urlparse
        return (urlparse(app_settings.get_api_url() or "").hostname or "").strip()
    except Exception:      # noqa: BLE001
        return ""


# ── Пароль SSH: хранение ─────────────────────────────────────────────────────────────
def _protect(plain: str) -> str:
    """Зашифровать пароль для хранения ('' — нечего хранить).

    DPAPI, как у «Входа по Windows» (§4.7): украденный файл настроек бесполезен на
    другом компьютере и под другой учётной записью. Совсем не хранить нельзя — тогда
    пароль пришлось бы вводить на каждую команду, и человек завёл бы его в блокноте."""
    if not plain:
        return ""
    import base64
    from data import security
    return base64.b64encode(security.os_protect(plain.encode("utf-8"))).decode("ascii")


def _password(server: dict) -> str:
    """Расшифрованный пароль ('' — его нет или расшифровать нечем)."""
    blob = (server or {}).get("pw") or ""
    if not blob:
        return ""
    try:
        import base64
        from data import security
        return security.os_unprotect(base64.b64decode(blob)).decode("utf-8", "replace")
    except Exception:      # noqa: BLE001
        _LOG.warning("[server-admin] сохранённый пароль не расшифровался")
        return ""


def _public(server: dict) -> dict:
    """Запись для страницы: БЕЗ пароля, только признак его наличия.

    Отдавать пароль обратно нельзя даже на петлю: страницу открывает браузерный движок,
    её содержимое попадает в память процесса и в инструменты разработчика, а смысл
    шифрования DPAPI в том, чтобы секрет не гулял в открытом виде."""
    out = {k: v for k, v in (server or {}).items() if k != "pw"}
    out["has_password"] = bool((server or {}).get("pw"))
    return out


# ── Выполнение команд ────────────────────────────────────────────────────────────────
def _ssh_argv(server: dict) -> list:
    ssh = shutil.which("ssh")
    if not ssh:
        raise RuntimeError("В системе нет клиента ssh. Установите OpenSSH Client "
                           "(Windows: «Дополнительные компоненты» → OpenSSH Client).")
    argv = [ssh] + list(_SSH_OPTS)
    key = (server.get("key") or "").strip()
    if key:
        #IdentitiesOnly: без него ssh-агент успевает предложить с десяток чужих ключей
        #и сервер разрывает соединение по «too many authentication failures» — при том,
        #что нужный ключ указан прямо здесь.
        argv += ["-i", key, "-o", "IdentitiesOnly=yes"]
    port = str(server.get("port") or "").strip()
    if port and port != "22":
        argv += ["-p", port]
    user = (server.get("user") or "root").strip()
    host = (server.get("host") or "").strip()
    if not host:
        raise RuntimeError("Не указан адрес сервера")
    argv.append(f"{user}@{host}")
    return argv


def _remember_host_keys(client) -> None:
    """Сделать доверие к ключу хоста ПОСТОЯННЫМ, а не разовым.

    🔥 Здесь был настоящий разрыв между комментарием и кодом (найден 29.08.2026
    статическим анализом). Ниже стояло `load_system_host_keys()` + `AutoAddPolicy`
    и пояснение, что это «то же самое, что StrictHostKeyChecking=accept-new».
    Это неверно: системный файл paramiko считает ТОЛЬКО ДЛЯ ЧТЕНИЯ, а `AutoAddPolicy`
    кладёт принятый ключ в память процесса. Своего файла не было — значит запомнить
    было некуда, и КАЖДОЕ подключение по паролю оказывалось «первым знакомством».
    Подмена сервера в этот момент не обнаруживалась ничем.

    Цена ровно там, где больно: путь с паролем существует для НОВОЙ машины, к
    которой ключ ещё не положен, — то есть человек как раз набирает пароль.

    Заводим СВОЙ файл рядом с данными программы, а не правим `~/.ssh/known_hosts`:
    paramiko перезаписывает его целиком и теряет хешированные записи и комментарии,
    сделанные обычным ssh. Системный продолжаем читать — чтобы программа и терминал
    одинаково отвечали на подмену ключа у уже известного хоста.
    """
    try:
        client.load_system_host_keys()
    except Exception:      # noqa: BLE001 — нет файла known_hosts, это нормально
        pass
    try:
        import app_paths
        path = os.path.join(app_paths.data_dir(), "known_hosts")
    except Exception:      # noqa: BLE001 — без пути просто останемся без памяти
        return
    try:
        #Имя файла ставится ПЕРВОЙ строкой самого load_host_keys, поэтому даже когда
        #файла ещё нет и загрузка падает, AutoAddPolicy уже знает, куда сохранять.
        client.load_host_keys(path)
    except Exception:      # noqa: BLE001 — файла нет: первое знакомство, так и надо
        pass


def _run_with_password(server: dict, command: str, timeout: int) -> dict:
    """Команда по паролю — через paramiko.

    Системный `ssh` этот путь не осилит: он запущен с `BatchMode=yes` и пароль не
    спрашивает, а без BatchMode процесс без консоли повис бы на приглашении навсегда.
    `sshpass` на Windows нет. Поэтому здесь единственная в модуле сторонняя библиотека,
    и импортируется она ЛЕНИВО — при входе по ключу её быть не обязано."""
    try:
        import paramiko
    except ImportError:
        return {"ok": False, "code": -1, "out": "",
                "err": "Для входа по паролю нужен пакет paramiko "
                       "(pip install paramiko). Либо используйте вход по ключу."}
    client = paramiko.SSHClient()
    try:
        _remember_host_keys(client)
        #AutoAdd принимает ТОЛЬКО НЕИЗВЕСТНЫЙ хост и, поскольку выше задан наш файл
        #known_hosts, СОХРАНЯЕТ принятый ключ в него. Смена ключа у уже известного
        #валится с BadHostKeyException — вот теперь это действительно
        #`StrictHostKeyChecking=accept-new`, а не «доверять чему угодно».
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
        client.connect(hostname=(server.get("host") or "").strip(),
                       port=int(server.get("port") or 22),
                       username=(server.get("user") or "root").strip(),
                       password=_password(server),
                       #Ключи не подставляем: раз выбран пароль, попытки агента только
                       #съедают лимит неудачных проверок и роняют соединение.
                       look_for_keys=False, allow_agent=False,
                       timeout=15, auth_timeout=20, banner_timeout=20)
        #SAST B601: выполнить произвольную команду на СВОЁМ сервере — и есть
        #назначение вкладки «Команды» (§16). Барьер здесь не в разборе строки, а
        #в том, что модуль подключается ТОЛЬКО к локальному серверу программы и
        #на боевом сервере его нет вовсе.
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)  # nosec B601
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return {"ok": code == 0, "code": code, "out": out, "err": err}
    except Exception as e:      # noqa: BLE001 — вкладка обязана показать причину
        return {"ok": False, "code": -1, "out": "", "err": str(e)}
    finally:
        try:
            client.close()
        except Exception:      # noqa: BLE001
            pass


def run(server: dict, command: str, timeout: int = _TIMEOUT_QUICK) -> dict:
    """Выполнить команду на сервере. Никогда не бросает — возвращает результат.

    Вкладка администратора должна показывать ОШИБКУ, а не пустоту: «ничего не
    произошло» — худший из возможных ответов, когда человек чинит боевой сервер."""
    #Пароль задан — идём парольным путём. Приоритет у пароля, а не у ключа: если человек
    #ввёл пароль, значит ключ на этой машине ещё не работает, и молча пробовать его
    #значило бы показывать «Permission denied» вместо подключения.
    if _password(server):
        return _run_with_password(server, command, timeout)
    try:
        argv = _ssh_argv(server) + ["--", command]
    except RuntimeError as e:
        return {"ok": False, "code": -1, "out": "", "err": str(e)}
    started = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout,
                           #creationflags: без него на Windows у собранного .exe
                           #вспыхивает чёрное окно консоли на каждую команду.
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        return {"ok": p.returncode == 0, "code": p.returncode, "out": out, "err": err,
                "seconds": round(time.time() - started, 2)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -2, "out": "",
                "err": f"Команда не ответила за {timeout} с и была прервана."}
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "code": -1, "out": "", "err": str(e)}


#Команды, которые способны необратимо снести сервер или данные. Не запрещаем — админ
#имеет право на всё, что может сделать в терминале, — но требуем осознанного
#подтверждения: разница между `rm -rf /root/gb-deploy` и `rm -rf /root/gb-deploy/tmp`
#это один символ, а последствия несопоставимы.
_DANGEROUS = re.compile(
    r"(\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*r[a-zA-Z]*f?\b"          # rm -rf и родня
    r"|\bmkfs\b|\bdd\s+.*\bof=/dev/"                               # форматирование диска
    r"|\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b"              # выключение
    r"|\buserdel\b|\bpasswd\b"                                     # учётки
    r"|\bdrop\s+(table|database)\b"                                # SQL
    r"|>\s*/dev/sd|\bchmod\s+-R\s+777\b)", re.I)


def is_dangerous(command: str) -> bool:
    return bool(_DANGEROUS.search(command or ""))


# ── Сведения об удалённой машине ─────────────────────────────────────────────────────
#Один заход по ssh вместо десяти: каждое соединение это рукопожатие в сотни миллисекунд,
#и вкладка, открывающаяся полторы секунды, ощущается сломанной.
_METRICS_SCRIPT = r"""
echo "###HOST"; hostname; uname -sr
echo "###UPTIME"; cat /proc/uptime 2>/dev/null | cut -d' ' -f1
echo "###LOAD"; cat /proc/loadavg 2>/dev/null | cut -d' ' -f1-3
echo "###CPU"; nproc 2>/dev/null
echo "###MEM"; grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo 2>/dev/null
echo "###DISK"; df -B1 --output=source,size,used,avail,pcent,target / 2>/dev/null | tail -1
echo "###SERVICES"; for s in gradebook caddy; do echo "$s=$(systemctl is-active $s 2>/dev/null)"; done
echo "###DIRS"; du -sb /root/gb-deploy /root/gb-backups 2>/dev/null
echo "###DB"; ls -l /root/gb-deploy/server/*.db 2>/dev/null | awk '{print $5" "$9}'
echo "###BACKUP"; ls -1t /root/gb-backups 2>/dev/null | head -1
echo "###END"
"""


def _section(text: str, name: str) -> str:
    """Кусок вывода между «###name» и следующим «###»."""
    marker = f"###{name}\n"
    if marker not in text:
        return ""
    rest = text.split(marker, 1)[1]
    return rest.split("###", 1)[0].strip()


def metrics(server: dict) -> dict:
    """Состояние удалённой машины одним запросом."""
    res = run(server, _METRICS_SCRIPT, timeout=40)
    if not res["ok"] and not res["out"]:
        return {"ok": False, "error": res["err"] or "Сервер не ответил"}
    text = res["out"]

    mem = {}
    for line in _section(text, "MEM").splitlines():
        k, _, v = line.partition(":")
        digits = v.strip().split()
        if digits and digits[0].isdigit():
            mem[k.strip()] = int(digits[0]) * 1024
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    swap_total = mem.get("SwapTotal", 0)

    disk_line = _section(text, "DISK").split()
    disk = {}
    if len(disk_line) >= 6:
        try:
            disk = {"device": disk_line[0], "total": int(disk_line[1]),
                    "used": int(disk_line[2]), "free": int(disk_line[3]),
                    "percent": disk_line[4], "mount": disk_line[5]}
        except ValueError:
            disk = {}

    services = {}
    for line in _section(text, "SERVICES").splitlines():
        name, _, state = line.partition("=")
        if name:
            services[name.strip()] = state.strip() or "unknown"

    dirs = []
    for line in _section(text, "DIRS").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            dirs.append({"path": parts[1], "size": int(parts[0])})

    db = {}
    db_line = _section(text, "DB").split(None, 1)
    if len(db_line) == 2 and db_line[0].isdigit():
        db = {"size": int(db_line[0]), "path": db_line[1]}

    host_lines = _section(text, "HOST").splitlines()
    try:
        uptime = float(_section(text, "UPTIME") or 0)
    except ValueError:
        uptime = 0.0
    try:
        cpu = int(_section(text, "CPU") or 1)
    except ValueError:
        cpu = 1

    return {
        "ok": True,
        "host": host_lines[0] if host_lines else "",
        "system": host_lines[1] if len(host_lines) > 1 else "",
        "uptime": uptime,
        "load": _section(text, "LOAD").split(),
        "cpu_count": cpu,
        "memory": {"total": total, "available": available,
                   "used": max(0, total - available), "swap_total": swap_total,
                   "swap_used": max(0, swap_total - mem.get("SwapFree", 0))},
        "disk": disk,
        "services": services,
        "dirs": dirs,
        "database": db,
        "latest_backup": _section(text, "BACKUP"),
    }


def tree(server: dict, path: str) -> dict:
    """Содержимое каталога на сервере с размерами — «что именно ест диск»."""
    safe = shlex.quote(path or "/root/gb-deploy")
    #du по каждому элементу отдельно: `du -s dir/*` считает только верхний уровень, а
    #нам нужен вес папки целиком — иначе картина «что занимает место» врёт.
    cmd = (f"cd {safe} 2>/dev/null && for f in * .[!.]*; do "
           f"[ -e \"$f\" ] || continue; "
           f"if [ -d \"$f\" ]; then printf 'd\\t%s\\t%s\\n' \"$(du -sb \"$f\" 2>/dev/null "
           f"| cut -f1)\" \"$f\"; else printf 'f\\t%s\\t%s\\n' "
           f"\"$(stat -c%s \"$f\" 2>/dev/null)\" \"$f\"; fi; done")
    res = run(server, cmd, timeout=90)
    items = []
    for line in (res["out"] or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        kind, size, name = parts
        items.append({"name": name, "dir": kind == "d",
                      "size": int(size) if size.isdigit() else 0})
    items.sort(key=lambda x: (-x["size"], x["name"].lower()))
    return {"path": path or "/root/gb-deploy", "items": items,
            "error": "" if res["ok"] or items else (res["err"] or "Каталог недоступен")}


# ── Резервные копии боевой машины ────────────────────────────────────────────────────
#Где лежат копии. Каталог тот же, что у ручных бэкапов команды, — чтобы копии, снятые
#кнопкой и снятые руками, не разъезжались по разным местам и не терялись.
BACKUP_DIR = "/root/gb-backups"
DEPLOY_DIR = "/root/gb-deploy"

#Что кладём в архив. НЕ весь каталог: venv и сборки сайта восстанавливаются из
#репозитория за минуты, а вот база и `.env` — нет. Причём именно ВМЕСТЕ: база
#зашифрована SQLCipher, и без ключа из `.env` архив бесполезен ровно так же, как его
#отсутствие. Это же делает архив опасным — см. предупреждение в интерфейсе.
_BACKUP_SCRIPT = r"""
set -e
mkdir -p {backup_dir}
cd {deploy_dir}
STAMP=$(date +%Y%m%d_%H%M%S)
NAME=backup-$STAMP.tar.gz
FREE=$(df -B1 --output=avail {backup_dir} | tail -1)
NEED=$(du -cb server/*.db server/.env 2>/dev/null | tail -1 | cut -f1)
if [ -n "$NEED" ] && [ "$FREE" -lt $((NEED * 3)) ]; then
  echo "МАЛО МЕСТА: нужно ~$((NEED * 3 / 1048576)) МБ, свободно $((FREE / 1048576)) МБ" >&2
  exit 28
fi
tar czf {backup_dir}/$NAME server/.env server/*.db 2>/dev/null
ls -l {backup_dir}/$NAME
echo "СОЗДАНО:$NAME"
"""


def make_backup(server: dict) -> dict:
    """Снять резервную копию на сервере. Возвращает {ok, name, log, hint}.

    Место проверяется ДО архивации: у боевого VPS диск занят на три четверти, и tar,
    оборвавшийся на середине, оставил бы битый архив, который выглядит как настоящий.
    Лучше честный отказ, чем копия, о непригодности которой узнают при восстановлении."""
    res = run(server, _BACKUP_SCRIPT.format(backup_dir=BACKUP_DIR, deploy_dir=DEPLOY_DIR),
              timeout=_TIMEOUT_LONG)
    log = (res["out"] or "") + (res["err"] or "")
    name = ""
    for line in log.splitlines():
        if line.startswith("СОЗДАНО:"):
            name = line.split(":", 1)[1].strip()
    if res["code"] == 28:
        return {"ok": False, "name": "", "log": log,
                "hint": "На сервере не хватает места. Удалите старые копии и повторите."}
    if not name:
        return {"ok": False, "name": "", "log": log,
                "hint": "Копия не создана. Проверьте, что каталог сервера на месте."}
    return {"ok": True, "name": name, "log": log,
            "hint": "Архив содержит ключ шифрования базы — не выкладывайте его в облако."}


def list_backups(server: dict) -> dict:
    """Копии на сервере: что есть, насколько свежее, сколько занимают."""
    cmd = (f"ls -1t {BACKUP_DIR} 2>/dev/null | head -40; echo '###SIZES'; "
           f"cd {BACKUP_DIR} 2>/dev/null && for f in $(ls -1t | head -40); do "
           f"printf '%s\\t%s\\t%s\\n' \"$(du -sb \"$f\" | cut -f1)\" "
           f"\"$(date -r \"$f\" '+%Y-%m-%d %H:%M')\" \"$f\"; done; "
           f"echo '###FREE'; df -B1 --output=avail {BACKUP_DIR} | tail -1")
    res = run(server, cmd, timeout=90)
    text = res["out"] or ""
    items = []
    for line in _section(text, "SIZES").splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            items.append({"size": int(parts[0]), "mtime": parts[1], "name": parts[2]})
    free = _section(text, "FREE").strip()
    return {"dir": BACKUP_DIR, "items": items,
            "free": int(free) if free.isdigit() else 0,
            "total_size": sum(i["size"] for i in items),
            "latest": items[0]["mtime"] if items else "",
            "error": "" if res["ok"] or items else (res["err"] or "Каталог недоступен")}


def download_backup(server: dict, name: str) -> dict:
    """Забрать копию на ЭТОТ компьютер.

    Смысл кнопки — увезти архив с той же машины, которая может сгореть. Копия, лежащая
    только на сервере, спасает от испорченных данных, но не от потери сервера."""
    if not name or "/" in name or "\\" in name or ".." in name:
        return {"ok": False, "path": "", "log": "Недопустимое имя файла."}
    try:
        import app_paths
        folder = os.path.join(app_paths.data_dir(), "server-backups")
    except Exception:      # noqa: BLE001
        folder = os.path.join(os.path.expanduser("~"), "GradeBookAI-backups")
    os.makedirs(folder, exist_ok=True)
    local = os.path.join(folder, name)
    res = _scp(server, f"{BACKUP_DIR}/{name}", local, pull=True)
    if not res["ok"]:
        return {"ok": False, "path": "", "log": res["log"]}
    size = os.path.getsize(local) if os.path.exists(local) else 0
    return {"ok": True, "path": local, "size": size, "log": res["log"]}


# ── Запуск и остановка служб ─────────────────────────────────────────────────────────
#Белый список. Ровно две наши службы и ровно три действия: `systemctl` умеет
#останавливать что угодно, включая ssh, — и тогда сервер станет недоступен НАВСЕГДА,
#потому что чинить его будет уже нечем. Свободные команды у админа есть во вкладке
#«Команды»; кнопка обязана быть безопасной по построению.
SERVICES = {"gradebook": "Сервер журнала", "caddy": "Веб-сервер и сертификаты"}
SERVICE_ACTIONS = ("start", "stop", "restart")


def service_action(server: dict, name: str, action: str) -> dict:
    """Запустить/остановить/перезапустить службу. Возвращает {ok, state, log, hint}."""
    if name not in SERVICES or action not in SERVICE_ACTIONS:
        return {"ok": False, "state": "", "log": "",
                "hint": "Такой службой отсюда управлять нельзя."}
    #`is-active` после действия возвращает ненулевой код для остановленной службы — это
    #не ошибка, а ответ, поэтому `|| true`, а результат читаем из вывода.
    cmd = (f"systemctl {action} {name}; sleep 2; systemctl is-active {name} || true")
    res = run(server, cmd, timeout=120)
    state = (res["out"] or "").strip().splitlines()[-1:] or [""]
    state = state[0].strip()
    expected = "inactive" if action == "stop" else "active"
    ok = state == expected
    hint = ""
    if action == "stop" and ok:
        hint = "Служба остановлена — сайт и приложение сейчас недоступны."
    elif not ok:
        hint = (f"Служба в состоянии «{state or 'неизвестно'}». "
                f"Посмотрите журнал: journalctl -u {name} -n 50")
    return {"ok": ok, "state": state, "log": (res["out"] or "") + (res["err"] or ""),
            "hint": hint}


def install_key(server: dict) -> dict:
    """Положить открытый ключ этого компьютера в authorized_keys на сервере.

    Ради этого вход по паролю и поддержан: один раз по паролю — и дальше можно ходить по
    ключу, а пароль стереть. Без такой кнопки человек оставил бы пароль навсегда,
    потому что «работает же»."""
    pub = ""
    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    #Берём ключ, указанный у сервера; нет — стандартные имена по убыванию надёжности.
    candidates = []
    if (server.get("key") or "").strip():
        candidates.append(server["key"].strip() + ".pub")
    candidates += [os.path.join(ssh_dir, n)
                   for n in ("gb_vps_ed25519.pub", "id_ed25519.pub", "id_rsa.pub")]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    pub = f.read().strip()
                break
            except OSError:
                continue
    if not pub:
        return {"ok": False, "log": "",
                "hint": "На этом компьютере не нашёлся открытый ключ (~/.ssh/*.pub). "
                        "Создайте его командой: ssh-keygen -t ed25519"}
    #grep -q перед дозаписью: повторное нажатие не должно плодить одинаковые строки.
    quoted = shlex.quote(pub)
    cmd = (f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
           f"chmod 600 ~/.ssh/authorized_keys && "
           f"(grep -qxF {quoted} ~/.ssh/authorized_keys || echo {quoted} >> ~/.ssh/authorized_keys) "
           f"&& echo ключ-на-месте")
    res = run(server, cmd, timeout=60)
    ok = "ключ-на-месте" in (res["out"] or "")
    return {"ok": ok, "log": (res["out"] or "") + (res["err"] or ""),
            "hint": ("Готово. Теперь можно убрать пароль из настроек сервера — "
                     "вход пойдёт по ключу." if ok else
                     "Не удалось записать ключ. Проверьте права пользователя на сервере.")}


# ── Перенос на другой сервер ─────────────────────────────────────────────────────────
#Перенос — это не одна кнопка, а последовательность, где каждый шаг может не удаться.
#Поэтому он разложен на ШАГИ с понятными названиями: человек видит, где именно встало,
#и может продолжить руками. «Мигрировало 40 %» без указания шага бесполезно.
MIGRATION_STEPS = [
    ("check_target", "Проверить связь с новым сервером"),
    ("check_space", "Проверить место на диске"),
    ("backup_source", "Снять резервную копию на старом сервере"),
    ("stop_source", "Остановить службу на старом сервере"),
    ("copy_data", "Скопировать базу, .env и файлы сайта"),
    ("install_service", "Прописать службу на новом сервере"),
    ("start_target", "Запустить службу на новом сервере"),
    ("verify", "Проверить, что новый сервер отвечает"),
]


def migration_plan(source: dict, target: dict) -> dict:
    """Что именно будет сделано. Показывается ДО запуска.

    Перенос боевой базы — операция, которую нельзя запускать «посмотреть, что будет».
    План с точными командами это единственный способ дать человеку проверить намерение
    до того, как оно исполнится."""
    return {
        "source": f"{source.get('user', 'root')}@{source.get('host', '')}",
        "target": f"{target.get('user', 'root')}@{target.get('host', '')}",
        "steps": [{"id": sid, "title": title} for sid, title in MIGRATION_STEPS],
        "warning": (
            "Старый сервер будет ОСТАНОВЛЕН на время копирования — сайт и приложение "
            "в это время недоступны. Данные со старого сервера не удаляются: он "
            "остаётся рабочим запасным вариантом, пока вы не убедитесь в новом."
        ),
    }


def _remote_free_bytes(server: dict) -> int:
    res = run(server, "df -B1 --output=avail / | tail -1")
    text = (res["out"] or "").strip()
    return int(text) if text.isdigit() else 0


def _remote_used_bytes(server: dict, path: str) -> int:
    res = run(server, f"du -sb {shlex.quote(path)} 2>/dev/null | cut -f1")
    text = (res["out"] or "").strip()
    return int(text) if text.isdigit() else 0


def migrate_step(step_id: str, source: dict, target: dict) -> dict:
    """Выполнить ОДИН шаг переноса. Возвращает {ok, log, hint}.

    По шагу за вызов — чтобы вкладка показывала ход, а не висела на несколько минут с
    крутилкой, и чтобы остановиться можно было между шагами, а не только в конце."""
    src_root = "/root/gb-deploy"

    if step_id == "check_target":
        res = run(target, "echo ok && test -d /root && echo root-ok")
        return {"ok": res["ok"] and "ok" in res["out"],
                "log": res["out"] + res["err"],
                "hint": "" if res["ok"] else
                        "Проверьте адрес, пользователя и что ваш открытый ключ добавлен "
                        "в ~/.ssh/authorized_keys на новом сервере."}

    if step_id == "check_space":
        need = _remote_used_bytes(source, src_root)
        free = _remote_free_bytes(target)
        #Полуторакратный запас — на распаковку и на то, что каталог за время переноса
        #подрастёт. Переносить «впритык» значит получить отказ на последнем шаге.
        ok = free > need * 1.5 and need > 0
        return {"ok": ok,
                "log": f"нужно ≈ {need / 1e6:.0f} МБ, свободно {free / 1e6:.0f} МБ",
                "hint": "" if ok else "На новом сервере мало места — освободите диск."}

    if step_id == "backup_source":
        stamp = time.strftime("%Y%m%d_%H%M%S")
        cmd = (f"mkdir -p /root/gb-backups && cd /root && "
               f"tar czf /root/gb-backups/premigrate-{stamp}.tar.gz "
               f"--exclude='gb-deploy/venv' --exclude='gb-deploy/webdist.bak-*' "
               f"gb-deploy && ls -l /root/gb-backups/premigrate-{stamp}.tar.gz")
        res = run(source, cmd, timeout=_TIMEOUT_LONG)
        return {"ok": res["ok"], "log": res["out"] + res["err"],
                "hint": "" if res["ok"] else "Без свежей копии перенос продолжать нельзя."}

    if step_id == "stop_source":
        res = run(source, "systemctl stop gradebook && systemctl is-active gradebook || true")
        return {"ok": True, "log": res["out"] + res["err"],
                "hint": "Сайт сейчас недоступен — это ожидаемо."}

    if step_id == "copy_data":
        #Копируем ЧЕРЕЗ ЭТОТ КОМПЬЮТЕР, а не сервер-серверу напрямую: прямой путь
        #требовал бы, чтобы у старого сервера был ключ от нового, то есть чтобы одна
        #боевая машина умела заходить на другую. Такой ключ потом никто не уберёт.
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"gb-migrate-{uuid.uuid4().hex[:8]}.tar.gz")
        pull = _scp(source, "/root/gb-backups/", tmp, pull=True, latest="premigrate-*.tar.gz")
        if not pull["ok"]:
            return {"ok": False, "log": pull["log"],
                    "hint": "Не удалось забрать архив со старого сервера."}
        push = _scp(target, "/root/gb-migrate.tar.gz", tmp, pull=False)
        try:
            os.remove(tmp)
        except OSError:
            pass
        if not push["ok"]:
            return {"ok": False, "log": push["log"],
                    "hint": "Не удалось положить архив на новый сервер."}
        res = run(target, "cd /root && tar xzf gb-migrate.tar.gz && rm -f gb-migrate.tar.gz "
                          "&& ls /root/gb-deploy | head -20", timeout=_TIMEOUT_LONG)
        return {"ok": res["ok"], "log": pull["log"] + push["log"] + res["out"] + res["err"],
                "hint": "" if res["ok"] else "Архив не распаковался на новом сервере."}

    if step_id == "install_service":
        res = run(target, _INSTALL_SERVICE, timeout=_TIMEOUT_LONG)
        return {"ok": res["ok"], "log": res["out"] + res["err"],
                "hint": "" if res["ok"] else
                        "Проверьте, что на новом сервере есть python3 и systemd."}

    if step_id == "start_target":
        res = run(target, "systemctl daemon-reload && systemctl enable --now gradebook "
                          "&& sleep 4 && systemctl is-active gradebook", timeout=120)
        return {"ok": "active" in res["out"], "log": res["out"] + res["err"],
                "hint": "" if "active" in res["out"] else
                        "Служба не поднялась: посмотрите journalctl -u gradebook -n 50."}

    if step_id == "verify":
        res = run(target, "curl -s -o /dev/null -w '%{http_code}' "
                          "http://127.0.0.1:8000/health", timeout=40)
        ok = res["out"].strip() == "200"
        return {"ok": ok, "log": f"/health → {res['out'].strip() or 'нет ответа'}",
                "hint": "" if ok else
                        "Сервер запущен, но не отвечает. Старый сервер ещё цел — "
                        "его можно вернуть командой systemctl start gradebook."}

    return {"ok": False, "log": "", "hint": f"Неизвестный шаг: {step_id}"}


#Разложено отдельной строкой, чтобы шаг читался: создаём окружение, ставим зависимости
#и прописываем ровно ту же службу, что работает сейчас.
#
#🔥 ЗДЕСЬ БЫЛ НАСТОЯЩИЙ ДЕФЕКТ, И СРАБОТАЛ БЫ ОН РОВНО В ДЕНЬ ПЕРЕЕЗДА (найдено
#04.09.2026). Пакеты ставились РУКОПИСНЫМ СПИСКОМ из пяти штук:
#    fastapi uvicorn sqlalchemy python-multipart httpx
#В нём не было НИЧЕГО из того, что добавлялось после его написания: `gostcrypto` и
#`cryptography` (хеш пароля и шифрование ПДн), `sqlcipher3-binary` (шифрование файла
#базы — то есть перенесённый сервер держал бы ПДн студентов открытым текстом),
#`python-jose` (JWT — вход не работал бы вовсе), `openpyxl`/`python-docx` (выгрузки),
#`webauthn`, `gigachat`, `pdfplumber`, `requests`, `pydantic`, `starlette`.
#Часть отказов была бы ГРОМКОЙ (сервер не поднялся), а часть — ТИХОЙ, и это хуже:
#шифрование базы просто не включилось бы, и узнали бы об этом на проверке.
#
#Правило то же, что уже записано для сборки .exe и для деплоя: **список зависимостей,
#перечисленный руками, верен ровно в день, когда его написали.** Ставим из файла.
_INSTALL_SERVICE = r"""
set -e
cd /root/gb-deploy
python3 -m venv venv 2>/dev/null || true
./venv/bin/pip install --quiet --upgrade pip
if [ -f server/requirements.txt ]; then
  ./venv/bin/pip install --quiet -r server/requirements.txt
else
  echo "НЕТ server/requirements.txt — ставить нечего, шаг провален" >&2
  exit 1
fi
cat > /etc/systemd/system/gradebook.service <<'UNIT'
[Unit]
Description=GradeBookAI API + site
After=network.target
[Service]
WorkingDirectory=/root/gb-deploy/server
ExecStart=/root/gb-deploy/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop uvloop --http httptools
Restart=always
User=root
[Install]
WantedBy=multi-user.target
UNIT
echo service-written
"""


def _sftp_copy(server: dict, remote: str, local: str, pull: bool) -> dict:
    """Копирование по паролю (SFTP через paramiko) — `scp` пароль ввести не умеет."""
    try:
        import paramiko
    except ImportError:
        return {"ok": False, "log": "Для входа по паролю нужен пакет paramiko."}
    client = paramiko.SSHClient()
    try:
        _remember_host_keys(client)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
        client.connect(hostname=(server.get("host") or "").strip(),
                       port=int(server.get("port") or 22),
                       username=(server.get("user") or "root").strip(),
                       password=_password(server),
                       look_for_keys=False, allow_agent=False,
                       timeout=15, auth_timeout=20, banner_timeout=20)
        sftp = client.open_sftp()
        try:
            if pull:
                sftp.get(remote, local)
            else:
                sftp.put(local, remote)
        finally:
            sftp.close()
        return {"ok": True, "log": f"скопировано: {os.path.basename(local)}\n"}
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "log": str(e)}
    finally:
        try:
            client.close()
        except Exception:      # noqa: BLE001
            pass


def _scp(server: dict, remote: str, local: str, pull: bool, latest: str = "") -> dict:
    """Копирование файла. `latest` — забрать самый свежий файл по маске из каталога."""
    if pull and latest:
        #Имя файла со временем известно только серверу — спрашиваем его самого. Делаем
        #это ДО выбора транспорта: вопрос одинаков и для ключа, и для пароля.
        got = run(server, f"ls -1t {shlex.quote(remote)}{latest} 2>/dev/null | head -1")
        remote = (got["out"] or "").strip()
        if not remote:
            return {"ok": False, "log": "На сервере не нашёлся нужный файл."}
        latest = ""
    if _password(server):
        return _sftp_copy(server, remote, local, pull)
    scp = shutil.which("scp")
    if not scp:
        return {"ok": False, "log": "В системе нет scp (установите OpenSSH Client)."}
    if pull and latest:
        #Имя архива со временем известно только серверу — спрашиваем его самого.
        got = run(server, f"ls -1t {shlex.quote(remote)}{latest} 2>/dev/null | head -1")
        remote = (got["out"] or "").strip()
        if not remote:
            return {"ok": False, "log": "На сервере не нашёлся архив резервной копии."}
    argv = [scp] + list(_SSH_OPTS)
    key = (server.get("key") or "").strip()
    if key:
        argv += ["-i", key, "-o", "IdentitiesOnly=yes"]
    port = str(server.get("port") or "").strip()
    if port and port != "22":
        argv += ["-P", port]
    addr = f"{server.get('user', 'root')}@{server.get('host', '')}"
    argv += [f"{addr}:{remote}", local] if pull else [local, f"{addr}:{remote}"]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=_TIMEOUT_LONG,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"ok": p.returncode == 0,
                "log": p.stdout.decode("utf-8", "replace") +
                       p.stderr.decode("utf-8", "replace")}
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "log": str(e)}


# ── Маршруты локального сервера ──────────────────────────────────────────────────────
def install(app, caller_ok) -> None:
    """Подключить раздел к ЛОКАЛЬНОМУ серверу программы.

    `caller_ok` — та же проверка «свой токен», что у остальных локальных маршрутов
    (см. `local_api._local_caller_ok`). Сервер слушает петлю, но петля доступна любому
    процессу и любой открытой в браузере странице, поэтому голого «мы на localhost»
    для выполнения команд на боевом сервере категорически мало."""
    from fastapi import Body, Query, Request
    from fastapi.responses import JSONResponse

    def _guard(request: Request):
        if not caller_ok(request.headers.get("authorization", "")):
            return JSONResponse({"detail": "Требуется авторизация"}, status_code=401)
        return None

    @app.get("/desk/servers")
    def _list(request: Request):
        bad = _guard(request)
        if bad:
            return bad
        #Путь к ключу отдаём — он не секрет (секрет лежит в самом файле) и человеку
        #нужно видеть, каким ключом идёт подключение. Пароль не отдаём НИКОГДА.
        return {"items": [_public(i) for i in ensure_seeded()],
                "default_key": _default_key(),
                "suggested_host": suggested_host()}

    @app.post("/desk/servers")
    def _save_one(request: Request, payload: dict = Body(...)):
        bad = _guard(request)
        if bad:
            return bad
        items = _load()
        sid = (payload.get("id") or "").strip() or uuid.uuid4().hex[:8]
        previous = _find(sid)
        row = {"id": sid,
               "name": (payload.get("name") or "").strip()[:60] or "Сервер",
               "host": (payload.get("host") or "").strip()[:120],
               "user": (payload.get("user") or "root").strip()[:60],
               "port": str(payload.get("port") or "22").strip()[:6],
               "key": (payload.get("key") or "").strip()[:400],
               "role": (payload.get("role") or "prod").strip()[:20]}
        #Пароль: пустое поле НЕ значит «сотри». Страница его не показывает (см. `_public`),
        #поэтому при обычном сохранении имени или порта поле придёт пустым — и молчаливое
        #стирание выбило бы доступ к серверу на ровном месте. Убрать пароль можно только
        #явным `clear_password`.
        if payload.get("clear_password"):
            row["pw"] = ""
        elif (payload.get("password") or "").strip():
            row["pw"] = _protect(payload["password"])
        else:
            row["pw"] = previous.get("pw", "")
        if not row["host"]:
            return JSONResponse({"detail": "Укажите адрес сервера"}, status_code=400)
        items = [i for i in items if i.get("id") != sid] + [row]
        _save(items)
        return {"ok": True, "item": _public(row), "items": [_public(i) for i in items]}

    @app.get("/desk/servers/{server_id}/backups")
    def _backups(request: Request, server_id: str):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        return list_backups(server)

    @app.post("/desk/servers/{server_id}/backups")
    def _make_backup(request: Request, server_id: str):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        out = make_backup(server)
        _LOG.info(f"[backup] {server.get('host')}: {'ok ' + out['name'] if out['ok'] else 'СБОЙ'}")
        return out

    @app.post("/desk/servers/{server_id}/backups/download")
    def _download_backup(request: Request, server_id: str, payload: dict = Body(...)):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        return download_backup(server, (payload.get("name") or "").strip())

    @app.post("/desk/servers/{server_id}/service")
    def _service(request: Request, server_id: str, payload: dict = Body(...)):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        name = (payload.get("name") or "").strip()
        action = (payload.get("action") or "").strip()
        #Остановка кладёт сайт для всего колледжа — требуем осознанного подтверждения,
        #как и у опасных команд. Первый вызов возвращает 409, второй (с confirm) делает.
        if action == "stop" and not payload.get("confirm"):
            return JSONResponse({"detail": "confirm-required", "name": name,
                                 "action": action}, status_code=409)
        out = service_action(server, name, action)
        _LOG.info(f"[service] {server.get('host')}: {action} {name} → {out['state']}")
        return out

    @app.post("/desk/servers/{server_id}/install-key")
    def _install_key(request: Request, server_id: str):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        return install_key(server)

    @app.delete("/desk/servers/{server_id}")
    def _delete(request: Request, server_id: str):
        bad = _guard(request)
        if bad:
            return bad
        items = [i for i in _load() if i.get("id") != server_id]
        _save(items)
        return {"ok": True, "items": [_public(i) for i in items]}

    @app.get("/desk/servers/{server_id}/metrics")
    def _metrics(request: Request, server_id: str):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        return metrics(server)

    @app.get("/desk/servers/{server_id}/tree")
    def _tree(request: Request, server_id: str, path: str = Query("")):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        return tree(server, path)

    @app.post("/desk/servers/{server_id}/exec")
    def _exec(request: Request, server_id: str, payload: dict = Body(...)):
        bad = _guard(request)
        if bad:
            return bad
        server = _find(server_id)
        if not server:
            return JSONResponse({"detail": "Сервер не найден"}, status_code=404)
        command = (payload.get("command") or "").strip()
        if not command:
            return JSONResponse({"detail": "Пустая команда"}, status_code=400)
        #Опасную команду выполняем только со ВТОРОГО раза — с явным «да, я понимаю».
        #Это не защита от злоумышленника (у него и так есть ssh), а защита от опечатки
        #в пути у уставшего человека: между `rm -rf /root/gb-deploy/tmp` и
        #`rm -rf /root/gb-deploy` разница в один символ, а последствия несопоставимы.
        if is_dangerous(command) and not payload.get("confirm"):
            return JSONResponse({"detail": "confirm-required",
                                 "command": command}, status_code=409)
        long_run = bool(payload.get("long"))
        res = run(server, command, timeout=_TIMEOUT_LONG if long_run else _TIMEOUT_QUICK)
        _LOG.info(f"[server-admin] {server.get('host')}: {command[:120]} → {res['code']}")
        return res

    @app.post("/desk/servers/migrate/plan")
    def _plan(request: Request, payload: dict = Body(...)):
        bad = _guard(request)
        if bad:
            return bad
        source, target = _find(payload.get("source", "")), _find(payload.get("target", ""))
        if not source or not target:
            return JSONResponse({"detail": "Выберите оба сервера"}, status_code=400)
        if source.get("id") == target.get("id"):
            return JSONResponse({"detail": "Это один и тот же сервер"}, status_code=400)
        return migration_plan(source, target)

    @app.post("/desk/servers/migrate/step")
    def _step(request: Request, payload: dict = Body(...)):
        bad = _guard(request)
        if bad:
            return bad
        source, target = _find(payload.get("source", "")), _find(payload.get("target", ""))
        step_id = (payload.get("step") or "").strip()
        if not source or not target:
            return JSONResponse({"detail": "Выберите оба сервера"}, status_code=400)
        out = migrate_step(step_id, source, target)
        _LOG.info(f"[migrate] {step_id}: {'ok' if out['ok'] else 'СБОЙ'}")
        return out

    #Маршруты локального сервера обязаны стоять ВЫШЕ заглушки SPA, иначе «всё
    #остальное → index.html» перехватит их и отдаст HTML вместо ответа.
    routes = app.router.routes
    mine = [r for r in routes if getattr(r, "path", "").startswith("/desk/servers")]
    for r in reversed(mine):
        routes.remove(r)
        routes.insert(0, r)
