r"""
pack_ota_bundle.py — упаковать собранный фронтенд в OTA-бандл для мобильного приложения.

    python tools/pack_ota_bundle.py web/dist server/ota_bundles/1.260812.0500.zip

Зовётся из `web/deploy/release-ota.ps1`. Отдельным файлом — не ради красоты, а потому что
в PowerShell на Windows НЕТ способа собрать zip с правильными именами:

  • `Compress-Archive` (PS 5.1) пишет разделители Windows: «assets\index-abc.js»;
  • `[System.IO.Compression.ZipFile]::CreateFromDirectory` в .NET Framework делает то же
    самое (проверено на этой машине сторожем в самом скрипте релиза).

А спецификация ZIP (APPNOTE, 4.4.17) требует ПРЯМОЙ слэш, и Java с Android читают имя
буквально: вместо папки «assets» на телефоне появляется ОДИН файл, в имени которого есть
обратный слэш. `index.html` после этого просит `/assets/index-abc.js`, которого больше
нет, и установка бандла не завершается. На устройстве это выглядело как
`finish_download_fail` — то есть как оборванная закачка, хотя сервер отдавал файл целиком
и с верной контрольной суммой.

Цена одной команды: обновления «по воздуху» не применялись НИ НА ОДНОМ телефоне около
месяца, и заметили это только по живой жалобе. Поэтому здесь же — проверка перед выходом:
ни одного обратного слэша в именах и обязательный `index.html` в корне.
"""
import os
import sys
import zipfile


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip().splitlines()[2])
        return 2
    src, dst = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    if not os.path.isdir(src):
        print(f"нет каталога сборки: {src}")
        return 2
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)

    count = 0
    skipped = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _dirs, files in os.walk(src):
            for name in sorted(files):
                full = os.path.join(root, name)
                # Имя ВНУТРИ архива задаём явно и приводим к прямым слэшам сами, не
                # полагаясь на разделитель текущей системы, — это и есть суть файла.
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                # ⚠️ Звук пасхалок в бандл НЕ кладём: он весит 4.2 МБ при всём бандле в
                # 4.9 МБ, то есть удвоил бы каждое обновление «по воздуху» ради того, что
                # у одного человека сработает раз в несколько месяцев. Картинки (260 КБ)
                # остаются — без них сцена не собирается вовсе, а без звука она просто
                # тихая: проигрывание и так обёрнуто в catch, autoplay браузеры режут.
                if rel.startswith("easter/snd/"):
                    skipped += 1
                    continue
                z.write(full, rel)
                count += 1

    if skipped:
        print(f"   пропущено (звук пасхалок, качается с сайта): {skipped}")

    with zipfile.ZipFile(dst) as z:
        names = z.namelist()
        bad = [n for n in names if "\\" in n]
        if bad:
            print(f"ОШИБКА: {len(bad)} имён с обратным слэшем, первое: {bad[0]}")
            return 1
        if "index.html" not in names:
            print("ОШИБКА: index.html не в корне архива — плагин отвергнет такой бандл")
            return 1

    print(f"упаковано файлов: {count}, размер: {os.path.getsize(dst) / 1048576:.2f} МБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
