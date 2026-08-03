"""
make_desktop_patch.py — собрать дельту между двумя сборками .exe и обновить манифест.

Запускается ПОСЛЕ сборки нового .exe (см. §8.1), обычно из деплой-скрипта:

    python tools/make_desktop_patch.py --old dist/GradeBookAI-3.5.5.exe \
                                       --new dist/GradeBookAI-3.5.6.exe \
                                       --out server/../downloads/updates

Кладёт в каталог обновлений: сам новый .exe (полная закачка — путь, который работает
всегда), патч `3.5.5-3.5.6.patch` и `manifest.json` с хешами.

── Почему zstd, а не bsdiff ──────────────────────────────────────────────────────────
`zstandard` (BSD, как и весь наш стек — GPL-зависимости тащить нельзя, §9) умеет
сжимать «относительно словаря»; словарём берём СТАРЫЙ .exe целиком — это и есть
дельта-режим (`zstd --patch-from`). Отдельная библиотека бинарного диффа не нужна, а на
клиенте пакет и так может пригодиться.

⚠️ **Патч публикуется, ТОЛЬКО если он реально выгоден.** onefile-сборка Nuitka СЖАТА, а
дельта между двумя сжатыми файлами может оказаться почти в размер самого файла: там, где
внутри поменялось немного, сжатый поток расходится целиком. Поэтому сборщик СРАВНИВАЕТ
размеры и при выигрыше меньше `--min-gain` (по умолчанию 40 %) патч не кладёт вовсе —
клиент честно скачает .exe целиком. Иначе мы бы гоняли «дельту» на 45 МБ вместо 48 и
называли это экономией.
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import desktop_update as DU        # noqa: E402

#Уровень сжатия: 19 — заметно плотнее обычного, но всё ещё разумно по времени сборки
#(патч собирается ОДИН раз при выкладке, а качают его все).
_LEVEL = 19


def build_patch(old_exe: str, new_exe: str, out_file: str) -> int:
    """Пишет дельту old→new. Возвращает размер патча в байтах (0 — не удалось)."""
    try:
        import zstandard
    except ImportError:
        print("zstandard не установлен — патч не собрать (pip install zstandard)")
        return 0
    with open(old_exe, "rb") as f:
        base = f.read()
    with open(new_exe, "rb") as f:
        target = f.read()
    cctx = zstandard.ZstdCompressor(level=_LEVEL,
                                    dict_data=zstandard.ZstdCompressionDict(base))
    data = cctx.compress(target)
    with open(out_file, "wb") as f:
        f.write(data)
    return len(data)


def main() -> int:
    ap = argparse.ArgumentParser(description="Сборка дельты обновления десктопа")
    ap.add_argument("--new", required=True, help="новый .exe (обязателен)")
    ap.add_argument("--old", default="", help="предыдущий .exe (без него будет только полная закачка)")
    ap.add_argument("--version", default="", help="версия нового .exe (по умолчанию — из APP_VERSION)")
    ap.add_argument("--old-version", default="", help="версия старого .exe")
    ap.add_argument("--out", required=True, help="каталог обновлений (downloads/updates)")
    ap.add_argument("--min-gain", type=float, default=0.40,
                    help="минимальный выигрыш патча против полной закачки (0.40 = 40%%)")
    args = ap.parse_args()

    if not os.path.isfile(args.new):
        print(f"нет файла: {args.new}")
        return 2
    version = DU.normalize(args.version) or _version_from_code()
    if not version:
        print("не удалось определить версию — задайте --version")
        return 2

    os.makedirs(args.out, exist_ok=True)
    full_name = f"GradeBookAI-{version}.exe"
    full_path = os.path.join(args.out, full_name)
    if os.path.abspath(args.new) != os.path.abspath(full_path):
        shutil.copy2(args.new, full_path)

    manifest = {
        "version": version,
        "full": {"file": full_name, "sha256": DU.sha256_file(full_path),
                 "size": os.path.getsize(full_path)},
        "patches": [],
    }

    if args.old and os.path.isfile(args.old):
        old_version = DU.normalize(args.old_version)
        if not old_version:
            print("не задана --old-version — патч пропущен (имя патча обязано её содержать)")
        else:
            name = DU.patch_name(old_version, version)
            path = os.path.join(args.out, name)
            size = build_patch(args.old, args.new, path)
            full_size = manifest["full"]["size"]
            gain = 1 - (size / full_size) if size and full_size else 0
            if not size:
                print("патч не собран — оставляем только полную закачку")
            elif gain < args.min_gain:
                #Именно тот случай, ради которого проверка и заведена, — см. шапку файла.
                print(f"патч {size / 1048576:.1f} МБ против {full_size / 1048576:.1f} МБ "
                      f"(выигрыш {gain:.0%} < {args.min_gain:.0%}) — НЕ публикуем")
                os.remove(path)
            else:
                manifest["patches"].append({
                    "from": old_version, "to": version, "file": name,
                    "sha256": DU.sha256_file(path), "size": size,
                    "target_sha256": manifest["full"]["sha256"],
                })
                #⚠️ Только символы, которые кодируются в cp1251: консоль Windows по
                #умолчанию именно в ней, и «→» роняет скрипт UnicodeEncodeError прямо
                #в момент выкладки (поймано на первом же прогоне).
                print(f"патч {old_version}->{version}: {size / 1048576:.1f} МБ "
                      f"(выигрыш {gain:.0%})")

    mpath = os.path.join(args.out, DU.MANIFEST_NAME)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"манифест: {mpath} (версия {version}, патчей {len(manifest['patches'])})")
    return 0


def _version_from_code() -> str:
    """Версия из data/core.py::APP_VERSION — чтобы не задавать её вторым местом руками."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "data", "core.py"), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("APP_VERSION"):
                    return DU.normalize(line.split("=", 1)[1])
    except OSError:
        pass
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
