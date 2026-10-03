r"""
build_ota_bundle.py — сборка OTA-бандла мобильного приложения (Capgo) из web/dist.

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ, а не «заархивировать папку».
Архив ОБЯЗАН содержать пути с ПРЯМЫМ слэшем: `assets/index-abc.js`. Так требует
спецификация ZIP (APPNOTE, 4.4.17.1), и так их ждёт распаковщик на Android.

Штатные средства Windows (`Compress-Archive` в Windows PowerShell 5.1) пишут разделитель
ОС, то есть `assets\index-abc.js`. Внешне архив выглядит целым: он открывается, файлы на
месте, контрольная сумма считается. Но на телефоне вместо папки `assets/` создаются файлы
с буквальными именами «assets\index-abc.js» в корне, `index.html` не находит свои скрипты,
бандл считается битым и откатывается на встроенный в APK.

Именно так молча сломались три бандла подряд (25–26.07.2026): сервер отдавал их корректно,
контрольные суммы сходились, а до телефонов обновление не доезжало.

Скрипт также:
  • кладёт файлы В КОРЕНЬ архива (не внутрь папки dist/) — этого ждёт Capgo;
  • считает sha256 и пишет latest.json рядом;
  • сам формирует версию по схеме 1.0.<YYMMDDHHMM> (она обязана расти).

Использование:
    python tools/build_ota_bundle.py                 # собрать в web/ota-out/
    python tools/build_ota_bundle.py --out D:/tmp    # другая папка назначения
    python tools/build_ota_bundle.py --check файл.zip  # проверить готовый архив
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "web", "dist")
DEFAULT_OUT = os.path.join(ROOT, "web", "ota-out")


def bundle_version(now: datetime = None) -> str:
    """1.0.<YYMMDDHHMM>. Версия обязана РАСТИ — Capgo сравнивает её со своей."""
    now = now or datetime.now()
    return "1.0." + now.strftime("%y%m%d%H%M")


def check_zip(path: str) -> list:
    """Проверить архив. Возвращает список проблем (пустой — всё в порядке)."""
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    if not names:
        return ["архив пуст"]
    bad = [n for n in names if "\\" in n]
    if bad:
        problems.append(
            f"{len(bad)} путей записаны через обратный слэш (нужен прямой), "
            f"например: {bad[0]}")
    if "index.html" not in names:
        problems.append("в КОРНЕ архива нет index.html — Capgo не примет такой бандл")
    #Частая ошибка: заархивировали саму папку, а не её содержимое.
    if any(n.startswith("dist/") for n in names):
        problems.append("файлы лежат внутри папки dist/ — они должны быть в корне архива")
    return problems


def build(dist_dir: str, out_dir: str, version: str) -> str:
    if not os.path.isdir(dist_dir):
        sys.exit(f"нет папки сборки: {dist_dir}\nсначала выполните: cd web && npm run build")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"{version}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _subdirs, files in os.walk(dist_dir):
            for name in files:
                full = os.path.join(folder, name)
                #Путь ОТНОСИТЕЛЬНО dist и строго через «/» — суть всего скрипта.
                rel = os.path.relpath(full, dist_dir).replace(os.sep, "/")
                z.write(full, arcname=rel)

    problems = check_zip(zip_path)
    if problems:
        #Не отдаём заведомо битый бандл: молча сломанное обновление хуже отсутствия.
        sys.exit("собранный архив не прошёл проверку:\n  - " + "\n  - ".join(problems))

    digest = hashlib.sha256(open(zip_path, "rb").read()).hexdigest()
    latest = {"version": version, "file": f"{version}.zip", "checksum": digest}
    with open(os.path.join(out_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    size_mb = os.path.getsize(zip_path) / 1024 / 1024
    print(f"собран {zip_path}  ({size_mb:.1f} МБ)")
    print(f"sha256: {digest}")
    print("latest.json записан рядом")
    print("\nдальше — залить на сервер:")
    print(f"  scp {version}.zip latest.json root@<vps>:/root/gb-deploy/server/ota_bundles/")
    print("  ssh root@<vps> systemctl restart gradebook")
    return zip_path


def main():
    ap = argparse.ArgumentParser(description="Сборка OTA-бандла из web/dist")
    ap.add_argument("--out", default=DEFAULT_OUT, help="куда положить архив")
    ap.add_argument("--dist", default=DIST, help="папка сборки веба")
    ap.add_argument("--version", default="", help="версия (по умолчанию 1.0.<YYMMDDHHMM>)")
    ap.add_argument("--check", default="", help="только проверить готовый архив")
    args = ap.parse_args()

    if args.check:
        problems = check_zip(args.check)
        if problems:
            print("НАЙДЕНЫ ПРОБЛЕМЫ:")
            for p in problems:
                print("  -", p)
            sys.exit(1)
        print("архив в порядке: пути через «/», index.html в корне")
        return

    build(args.dist, args.out, args.version or bundle_version())


if __name__ == "__main__":
    main()
