# -*- coding: utf-8 -*-
"""build_release.py — собрать НЕИЗМЕНЯЕМЫЙ артефакт релиза сервера.

━━ ЗАЧЕМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Деплой у нас до сих пор — это `scp` каталога `server/app` ПЛЮС отдельный `scp`
корневых общих модулей. Этот способ ронял прод ДВАЖДЫ (уехала половина кода) и
один раз дал ложную уверенность: девять совпавших SHA-256 при том, что файлы
приехали из ДРУГОЙ ветки. Файлы совпали — происхождение нет.

Артефакт закрывает оба случая по построению:
  • он ОДИН. Нельзя «забыть довезти» модуль: чего нет в архиве, того нет нигде;
  • он ПОДПИСАН содержимым (sha256) и НАЗВАН происхождением (версия + коммит);
  • он НЕИЗМЕНЯЕМ: на сервере он разворачивается в свой каталог и никогда не
    правится на месте. Откат — это переключение ссылки, а не «залить старое
    поверх нового», после которого состояние не знает никто.

━━ ЧТО ВНУТРИ И ЧЕГО ТАМ НЕТ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Внутри: server/app, корневые общие модули, собранный сайт, список зависимостей,
манифест с хешами.

⚠️ СОСТОЯНИЯ ВНУТРИ НЕТ И БЫТЬ НЕ ДОЛЖНО: ни `.env`, ни базы, ни `downloads/`,
ни `ota_bundles/`, ни резервных копий. Артефакт разворачивается рядом с ними, а
не поверх. Это не аккуратность, а условие: артефакт с ключом от базы внутри
нельзя ни хранить, ни пересылать, а обновление, которое трогает состояние, —
это уже не обновление.

━━ СПИСОК КОРНЕВЫХ МОДУЛЕЙ ВЫВОДИТСЯ, А НЕ ПИШЕТСЯ РУКАМИ ━━━━━━━━━━━━━━━━━━━━
Ровно на этом уже обожглись при сборке .exe: список вёлся руками, с припиской
«проверено полным перебором». Приписка была верна в день, когда её написали, и
молча устарела. Любой «проверенный перебором» список в комментарии — это снимок
значения, и он откажет именно в тот день, когда понадобится.

━━ ВОСПРОИЗВОДИМОСТЬ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Два запуска на одном коммите дают ПОБАЙТОВО ОДИНАКОВЫЙ архив: время, владелец и
права в записях зафиксированы, порядок отсортирован, штамп gzip обнулён. Без
этого «сверить хеш» ничего не значит — он различался бы от запуска к запуску, и
единственным способом проверить поставку осталось бы доверие.

Запуск:
    python -X utf8 tools/build_release.py                 # собрать
    python -X utf8 tools/build_release.py --check         # только проверить состав
"""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "dist-release")

# Что кладём в архив, кроме выведенных корневых модулей.
SERVER_APP = os.path.join(ROOT, "server", "app")
WEB_DIST = os.path.join(ROOT, "web", "dist")

# ⚠️ Фиксированные метаданные записей: без них в архив попадают время сборки и
# имя пользователя, и один и тот же код даёт разные архивы.
FIXED_MTIME = 0
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "tests"}


def _run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding="utf-8").strip()


def app_version() -> str:
    """Версия — из ЕДИНСТВЕННОГО места (desktop_update.APP_VERSION)."""
    src = io.open(os.path.join(ROOT, "desktop_update.py"), encoding="utf-8").read()
    m = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", src)
    if not m:
        raise SystemExit("не нашёл APP_VERSION в desktop_update.py")
    return m.group(1)


def version_slug(version: str) -> str:
    """Версия в виде, пригодном для имени файла и каталога.

    APP_VERSION у нас человекочитаемая («Release 3.8.2»), а в имени каталога на
    сервере пробелам делать нечего.
    """
    return re.sub(r"[^A-Za-z0-9.]+", "-", version).strip("-").lower()


def _local_module_names() -> set[str]:
    names = set()
    for entry in os.listdir(ROOT):
        full = os.path.join(ROOT, entry)
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif os.path.isdir(full) and os.path.exists(os.path.join(full, "__init__.py")):
            names.add(entry)
    return names


def _imported_names(path: str, top_level_only: bool = False) -> set[str]:
    """Имена верхнего уровня импорта в файле.

    `top_level_only=True` — только те импорты, что исполняются ПРИ ЗАГРУЗКЕ
    модуля. Разница здесь не academic, она поймана на живом коде:

    🔥 `schedule/overrides.py` и `schedule/store.py` внутри функций импортируют
    `data.core` и `sync.sync_runner` — ДЕСКТОПНЫЕ пакеты. На сервере эти ветки не
    исполняются никогда (там своя реализация), но слепой обход «всех импортов»
    притащил в артефакт `data/`, `sync/` и `desktop/` целиком. Последнее — прямое
    нарушение §16: в `desktop/server_admin.py` лежит выполнение команд по SSH, и
    единственное, что отделяет его от боевого сервера, — то, что этого файла там
    НЕТ. Автоматика, которая его туда привезёт, хуже отсутствия автоматики.
    """
    try:
        tree = ast.parse(io.open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):
        return set()
    out = set()
    nodes = tree.body if top_level_only else ast.walk(tree)
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def needed_root_modules() -> list[str]:
    """Корневые модули и пакеты, без которых server/app не поднимется.

    Правило в два шага, и оба нужны:

    1. НАЧАЛЬНЫЙ НАБОР — всё, что `server/app` импортирует ХОТЬ ГДЕ, включая
       импорты внутри функций. Ленивый импорт в серверном коде означает, что
       сервер этим модулем всё-таки пользуется, просто не на старте.

    2. РАСШИРЕНИЕ — только по импортам УРОВНЯ МОДУЛЯ. Они исполняются при
       загрузке, то есть их отсутствие роняет сервер гарантированно. Ленивые
       импорты ВНУТРИ общих модулей не следуем: там они ведут в десктопную
       половину продукта (см. `_imported_names`).

    ⚠️ Граница названа честно: ленивый импорт общего модуля из общего модуля,
    нужный именно серверу, этим правилом не поймается. Поэтому список — не
    единственная защита: `server/tests/test_release_artifact.py` проверяет
    состав, а смоук-прогон поднимает сервер ИЗ АРХИВА и ходит по живым адресам.
    Статический вывод ошибается тихо, запуск — громко.
    """
    local = _local_module_names()
    seen: set[str] = set()
    frontier: set[str] = set()

    for base, dirs, files in os.walk(SERVER_APP):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            if name.endswith(".py"):
                frontier |= _imported_names(os.path.join(base, name)) & local

    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        paths = []
        if os.path.exists(os.path.join(ROOT, name + ".py")):
            paths.append(os.path.join(ROOT, name + ".py"))
        pkg = os.path.join(ROOT, name)
        if os.path.isdir(pkg):
            for base, dirs, files in os.walk(pkg):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                paths += [os.path.join(base, f) for f in files if f.endswith(".py")]
        for p in paths:
            frontier |= (_imported_names(p, top_level_only=True) & local) - seen

    # `app` — это сам server/app, он едет отдельно и корневым модулем не является.
    return sorted(n for n in seen if n != "app")


def _collect(src_dir: str, arc_prefix: str) -> list[tuple[str, str]]:
    """(путь на диске, имя в архиве), отсортировано — порядок влияет на хеш."""
    out = []
    for base, dirs, files in os.walk(src_dir):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(files):
            if name.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(base, name)
            rel = os.path.relpath(full, src_dir).replace(os.sep, "/")
            out.append((full, f"{arc_prefix}/{rel}"))
    return sorted(out, key=lambda p: p[1])


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gather(include_web: bool = True) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    entries += _collect(SERVER_APP, "app")

    for name in needed_root_modules():
        single = os.path.join(ROOT, name + ".py")
        if os.path.exists(single):
            entries.append((single, f"root/{name}.py"))
        pkg = os.path.join(ROOT, name)
        if os.path.isdir(pkg):
            entries += _collect(pkg, f"root/{name}")

    entries.append((os.path.join(ROOT, "server", "requirements.txt"), "requirements.txt"))

    if include_web:
        if not os.path.isdir(WEB_DIST):
            raise SystemExit(
                "нет web/dist — сначала `cd web && npm run build`.\n"
                "Артефакт без сайта разворачивать нельзя: сервер отдаёт SPA сам, "
                "и на боевой машине это была бы пустая страница вместо журнала."
            )
        entries += _collect(WEB_DIST, "webdist")

    return sorted(entries, key=lambda p: p[1])


def build(include_web: bool = True) -> str:
    version = app_version()
    slug = version_slug(version)
    commit = _run("git", "rev-parse", "HEAD")
    short = commit[:12]
    dirty = bool(_run("git", "status", "--porcelain"))

    entries = gather(include_web)
    files = {arc: _sha256(src) for src, arc in entries}

    manifest = {
        "product": "GradeBookAI",
        "version": version,
        "commit": commit,
        # ⚠️ Грязное дерево помечаем ЧЕСТНО. Такой артефакт нельзя связать с
        # коммитом, а значит нельзя и воспроизвести — на бой ему нельзя.
        "dirty_worktree": dirty,
        "root_modules": needed_root_modules(),
        "includes_web": include_web,
        "file_count": len(files),
        "files": files,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2,
                                sort_keys=True).encode("utf-8")

    os.makedirs(OUT_DIR, exist_ok=True)
    name = f"gradebook-{slug}-{short}.tar.gz"
    out_path = os.path.join(OUT_DIR, name)

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        def _add(arcname: str, data: bytes | None = None, src: str | None = None):
            info = tarfile.TarInfo(arcname)
            info.mtime = FIXED_MTIME
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            if data is not None:
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
            else:
                info.size = os.path.getsize(src)
                # Права нормализуем: у файла, приехавшего с Windows, их всё равно нет.
                info.mode = 0o644
                with open(src, "rb") as fh:
                    tar.addfile(info, fh)

        _add("MANIFEST.json", data=manifest_bytes)
        for src, arc in entries:
            _add(arc, src=src)

    # mtime=0 в gzip: иначе штамп времени сборки попадает в первые байты файла.
    with open(out_path, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz:
            gz.write(raw.getvalue())

    digest = _sha256(out_path)
    with io.open(out_path + ".sha256", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"{digest}  {name}\n")

    print(f"версия:          {version}")
    print(f"коммит:          {short}{'  ⚠️ ГРЯЗНОЕ ДЕРЕВО' if dirty else ''}")
    print(f"корневые модули: {', '.join(manifest['root_modules'])}")
    print(f"файлов:          {len(files)}")
    print(f"архив:           {out_path}")
    print(f"размер:          {os.path.getsize(out_path):,} байт")
    print(f"sha256:          {digest}")
    if dirty:
        print("\n⚠️ Дерево грязное: артефакт помечен как невоспроизводимый.")
        print("   На бой такой не выкладывать — его нельзя связать с коммитом.")
    return out_path


def check() -> None:
    """Показать состав, ничего не собирая."""
    mods = needed_root_modules()
    print(f"версия:  {app_version()}")
    print(f"корневые модули ({len(mods)}): {', '.join(mods)}")
    missing = [m for m in mods
               if not os.path.exists(os.path.join(ROOT, m + ".py"))
               and not os.path.isdir(os.path.join(ROOT, m))]
    if missing:
        raise SystemExit(f"выведены модули, которых нет на диске: {missing}")
    print("web/dist:", "есть" if os.path.isdir(WEB_DIST) else "НЕТ (нужен npm run build)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="только показать состав")
    ap.add_argument("--no-web", action="store_true",
                    help="без web/dist (для проверки серверной части)")
    ap.add_argument("--clean", action="store_true", help="очистить dist-release перед сборкой")
    args = ap.parse_args()

    if args.check:
        check()
        return
    if args.clean and os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    build(include_web=not args.no_web)


if __name__ == "__main__":
    sys.exit(main())
