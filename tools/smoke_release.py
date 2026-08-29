# -*- coding: utf-8 -*-
"""smoke_release.py — поднять сервер ИЗ АРТЕФАКТА и проверить, что он живой.

━━ ЗАЧЕМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Тесты проверяют код в дереве разработки. Артефакт — это ДРУГАЯ раскладка: `app/`
рядом с `root/`, общие модули на PYTHONPATH, сайт из `webdist/`. Всё, что связано
именно с раскладкой, тесты не видят по построению — а роняло нас это дважды
(частичный деплой) и один раз в .exe (свои файлы в корне чужой распаковки).

Единственный способ узнать, что артефакт рабочий, — запустить его. Статический
вывод ошибается тихо, запуск — громко.

━━ ЭТО ЖЕ И STAGING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
С ключом `--stay` тот же скрипт оставляет экземпляр работать: получается стенд на
машине разработчика, куда раскатан РОВНО тот артефакт, что поедет на бой.

🔒 ДАННЫЕ ЗДЕСЬ ТОЛЬКО ВЫДУМАННЫЕ, И ЭТО НЕ УДОБСТВО, А ЗАПРЕТ. Копия боевой базы
на личной машине — это персональные данные студентов на оборудовании разработчика,
то есть ровно то, что запрещает п. 5.2.4.1 политики ВСГУТУ. Никакой ключ этого
скрипта не умеет взять живую базу — брать её неоткуда по построению.
Побочная польза: на выдуманных данных видно то, что на знакомых глаз пропускает.

Запуск:
    python -X utf8 tools/smoke_release.py                 # собрать? нет — взять свежий
    python -X utf8 tools/smoke_release.py --stay          # оставить стенд работать
    python -X utf8 tools/smoke_release.py --artifact <файл>
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADMIN_LOGIN = "smoke_admin"
ADMIN_PASSWORD = "SmokeStand-" + secrets.token_hex(6)
#Стенд представляется ХОСТОМ. Так же выглядит настоящая первичная настройка на
#машине ВСГУТУ: барьер устройства применяется и к заведению первого
#администратора (`ensure_device_allowed` там зовётся НАПРЯМУЮ, а не через
#`device_barrier_applies`, поэтому веб-послабление на него не действует).
#Поймано первым же смоук-прогоном — по коду это неочевидно.
HOST_DEVICE_ID = "smoke-" + secrets.token_hex(8)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _latest_artifact() -> str:
    found = sorted(glob.glob(os.path.join(ROOT, "dist-release", "gradebook-*.tar.gz")),
                   key=os.path.getmtime, reverse=True)
    if not found:
        raise SystemExit("нет артефакта — сначала `python -X utf8 tools/build_release.py`")
    return found[0]


def _request(url, data=None, headers=None, method=None, timeout=15):
    body = None
    hdrs = {"X-Client": "web", "X-Device-Id": HOST_DEVICE_ID}
    hdrs.update(headers or {})
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        # nosec B310 — адрес собирается здесь же из 127.0.0.1 и выбранного порта
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Stand:
    """Развёрнутый из артефакта экземпляр: своя папка, своя база, свой порт."""

    def __init__(self, artifact: str, workdir: str | None = None, port: int | None = None):
        self.artifact = artifact
        self.dir = workdir or tempfile.mkdtemp(prefix="gb-smoke-")
        self.port = port or _free_port()
        self.proc: subprocess.Popen | None = None
        self.owns_dir = workdir is None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def unpack(self) -> dict:
        code = os.path.join(self.dir, "release")
        os.makedirs(code, exist_ok=True)
        with tarfile.open(self.artifact, "r:gz") as tar:
            tar.extractall(code)
        manifest = json.load(open(os.path.join(code, "MANIFEST.json"), encoding="utf-8"))
        print(f"  версия:  {manifest['version']} ({manifest['commit'][:12]})")
        print(f"  файлов:  {manifest['file_count']}")
        if manifest.get("dirty_worktree"):
            print("  ⚠️ артефакт собран из грязного дерева — для стенда годится, для боя нет")
        self.code = code
        return manifest

    def start(self) -> None:
        env = dict(os.environ)
        env.update({
            #Своя пустая база во временной папке. Боевую сюда не подставить.
            "GRADEBOOK_DB_URL": "sqlite:///" + os.path.join(self.dir, "smoke.db").replace("\\", "/"),
            #Секрет одноразовый: стенд не должен принимать боевые токены, а боевой —
            #стендовые. Общий секрет сделал бы их взаимозаменяемыми.
            "GRADEBOOK_JWT_SECRET": secrets.token_hex(32),
            "GRADEBOOK_WEB_DIST": os.path.join(self.code, "webdist"),
            "GRADEBOOK_HOST_DEVICE_ID": HOST_DEVICE_ID,
            "GRADEBOOK_DOWNLOADS": os.path.join(self.dir, "downloads"),
            "GRADEBOOK_OTA_DIR": os.path.join(self.dir, "ota"),
            "PYTHONPATH": os.path.join(self.code, "root"),
            "PYTHONUTF8": "1",
        })
        os.makedirs(env["GRADEBOOK_DOWNLOADS"], exist_ok=True)
        os.makedirs(env["GRADEBOOK_OTA_DIR"], exist_ok=True)

        log = open(os.path.join(self.dir, "server.log"), "wb")
        self.log_path = log.name
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=self.code, env=env, stdout=log, stderr=subprocess.STDOUT,
        )

    def wait_health(self, seconds: int = 60) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise SystemExit("сервер упал на старте:\n" + self._tail())
            try:
                code, _ = _request(self.base + "/health", timeout=3)
                if code == 200:
                    return
            except Exception:
                pass
            time.sleep(1)
        raise SystemExit(f"/health не ответил за {seconds} с:\n" + self._tail())

    def _tail(self, lines: int = 40) -> str:
        try:
            data = open(self.log_path, "rb").read().decode("utf-8", "replace")
        except OSError:
            return "(лог недоступен)"
        return "\n".join(data.splitlines()[-lines:])

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.owns_dir:
            shutil.rmtree(self.dir, ignore_errors=True)


def checks(stand: Stand) -> list[tuple[str, bool, str]]:
    """Проверки идут ПО ЖИВЫМ АДРЕСАМ, а не по коду.

    Набор намеренно короткий: смоук отвечает на вопрос «поднялось и отвечает ли
    по существу», а не заменяет 1151 серверный тест. Длинный смоук начинают
    пропускать, а пропущенный гейт — это отсутствующий гейт.
    """
    out = []

    def add(name, ok, detail=""):
        out.append((name, ok, detail))

    code, body = _request(stand.base + "/health")
    add("/health отвечает 200", code == 200, f"код {code}")

    # SPA: сервер обязан отдавать сайт САМ — на бою это один адрес с API.
    code, body = _request(stand.base + "/")
    ok = code == 200 and (b'<div id="app"' in body or b"assets/" in body)
    add("сайт отдаётся с того же адреса", ok, f"код {code}, {len(body)} байт")

    # Кабинет без токена обязан отвечать отказом. Проверка не «что работает», а
    # «что закрыто» — её отсутствие однажды и делает журнал публичным.
    code, _ = _request(stand.base + "/web/student/overview")
    add("кабинет закрыт без токена", code in (401, 403), f"код {code}")

    code, body = _request(stand.base + "/auth/bootstrap-admin",
                          data={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD,
                                "full_name": "Смоук Администратор"})
    add("заводится первый администратор", code == 200, f"код {code} {body[:120]!r}")

    token = ""
    if code == 200:
        try:
            token = json.loads(body).get("access_token", "")
        except ValueError:
            pass
    add("выдан токен доступа", bool(token))

    if token:
        auth = {"Authorization": "Bearer " + token}
        #⚠️ «/me/prefs», а не «/me»: маршрута «/me» не существует, и до 29.08.2026
        #такой запрос уходил в SPA-заглушку и получал 200 со страницей. Проверка
        #«кабинет открывается» тогда проходила, ни разу не открыв кабинет.
        code, body = _request(stand.base + "/me/prefs", headers=auth)
        add("кабинет открывается по токену", code == 200, f"код {code}")

        # Корневые общие модули: адрес обновлений читает desktop_update, то есть
        # ответ 200 доказывает, что PYTHONPATH раскладки артефакта работает.
        code, body = _request(stand.base + "/desktop/updates")
        add("общие корневые модули подхватились", code == 200, f"код {code}")

    ok, detail = _import_every_module(stand)
    add("каждый модуль артефакта импортируется", ok, detail)
    return out


def _import_every_module(stand: Stand):
    """Импортировать ВСЁ, что лежит в архиве, в раскладке артефакта.

    🔥 Зачем сверх обычных проверок. Список корневых модулей выводится статически
    (по импортам уровня модуля), и у этого правила есть честная дыра: модуль,
    который общий модуль импортирует ЛЕНИВО и который всё-таки нужен серверу, в
    список не попадёт. Статический вывод ошибается ТИХО — сервер поднимется и
    упадёт позже, на первом обращении к этой ветке, у человека.

    Импорт каждого файла закрывает почти всю эту дыру за секунды: любой ленивый
    импорт внутри уже привезённого модуля разрешается здесь. Остаётся только
    импорт внутри функции, которая при импорте не исполняется, — от него
    защищают уже обычные тесты.
    """
    import subprocess as _sp

    probe = r"""
import os, sys, importlib
root = os.path.join(os.getcwd(), "root")
sys.path.insert(0, root)
bad = []
for base in ("app", "root"):
    top = os.path.join(os.getcwd(), base)
    anchor = os.getcwd() if base == "app" else root
    for dirpath, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if not f.endswith(".py") or f == "__init__.py":
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), anchor)
            mod = rel[:-3].replace(os.sep, ".")
            try:
                importlib.import_module(mod)
            except Exception as e:
                bad.append(mod + ": " + type(e).__name__ + ": " + str(e)[:90])
print("|".join(bad))
"""

    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.join(stand.code, "root")
        env["PYTHONUTF8"] = "1"
        #Ключи не нужны: проверяем импортируемость, а не работу с базой.
        env["GRADEBOOK_DB_URL"] = "sqlite:///" + os.path.join(stand.dir, "probe.db").replace("\\\\", "/")
        res = _sp.run([sys.executable, "-c", probe], cwd=stand.code, env=env,
                      capture_output=True, text=True, timeout=180)
    except Exception as e:                       # noqa: BLE001
        return False, f"не удалось запустить проверку: {e}"
    bad = (res.stdout or "").strip()
    if res.returncode != 0:
        return False, (res.stderr or "")[-200:]
    if bad:
        return False, bad.replace("|", "; ")[:300]
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", help="путь к архиву (по умолчанию — свежий)")
    ap.add_argument("--port", type=int, help="порт (по умолчанию свободный)")
    ap.add_argument("--dir", help="куда развернуть (по умолчанию временная папка)")
    ap.add_argument("--stay", action="store_true",
                    help="не гасить стенд после проверок (staging на этой машине)")
    args = ap.parse_args()

    artifact = args.artifact or _latest_artifact()
    print(f"== Смоук-прогон артефакта ==\n  файл:    {os.path.basename(artifact)}")

    stand = Stand(artifact, workdir=args.dir, port=args.port)
    failures = 0
    try:
        stand.unpack()
        print(f"  адрес:   {stand.base}")
        stand.start()
        stand.wait_health()
        print()
        for name, ok, detail in checks(stand):
            mark = "OK   " if ok else "СБОЙ "
            print(f"  [{mark}] {name}" + (f"  — {detail}" if detail and not ok else ""))
            failures += 0 if ok else 1

        print()
        if failures:
            print(f"🔥 ПРОВАЛЕНО ПРОВЕРОК: {failures}")
            print("Последние строки лога сервера:")
            print(stand._tail())
        else:
            print("Все проверки пройдены: артефакт разворачивается и работает.")

        if args.stay:
            print(f"\nСтенд оставлен работать: {stand.base}")
            print(f"  вход:   {ADMIN_LOGIN} / {ADMIN_PASSWORD}")
            print(f"  папка:  {stand.dir}")
            print("  Ctrl+C — остановить.")
            stand.owns_dir = False
            try:
                stand.proc.wait()
            except KeyboardInterrupt:
                print("\nостановлено")
    finally:
        if not args.stay:
            stand.stop()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
