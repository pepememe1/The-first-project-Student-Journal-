"""
build_mascot_sprites.py — пережать спрайты эмоций Вектора из PNG в WebP.

    python tools/build_mascot_sprites.py            # показать, что будет сделано
    python tools/build_mascot_sprites.py --apply    # пережать и удалить исходные PNG

━━ ЗАЧЕМ ━━
Живой отзыв Ярослава (11-12.08.2026): обновления «по воздуху» не доезжают до телефона.
Журнал на устройстве показал `finish_download_fail` и `Software caused connection abort`
на каждой попытке — то есть закачка обрывается, не дойдя до конца. Разбор веса бандла
объяснил почему:

    маскот  7.03 МБ  ← тридцать спрайтов PNG по ~170 КБ + анимации
    шрифты  1.29 МБ
    код     0.34 МБ
    -----------------
    итого   8.7 МБ на КАЖДОЕ обновление интерфейса

То есть телефон по мобильной сети тянул восемь с лишним мегабайт, из которых семь —
картинки, не менявшиеся месяцами, и обрывался. Пережатие в WebP уменьшает спрайты
примерно в пять раз (замерено на реальных файлах: 172 КБ → 34 КБ) при том же виде:
формат поддерживает альфа-канал, а Android WebView и все браузеры проекта читают его
с незапамятных версий — анимации маскота в `mascot/anim/` уже лежат в WebP.

━━ ГРАНИЦЫ ━━
* Трогаем ТОЛЬКО веб-копию (`web/public/mascot/*.png`). Нативный десктоп берёт арт из
  `emotions/` и в WebP не нуждается: там нет ни канала связи, ни счёта за мегабайты.
* Исходные PNG после пережатия УДАЛЯЮТСЯ (по `--apply`). Оставить их — значит не
  выиграть ничего: в бандл попадает всё содержимое `public/`, и лишний комплект
  продолжал бы ездить на телефоны. Исходники арта Арины хранятся отдельно, в `emotions/`.
* Качество 82 и `method=6` — выбраны замером: ниже 80 на плашках появляется грязь
  вокруг усов, выше 88 файл растёт без видимой разницы.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPRITES = os.path.join(ROOT, "web", "public", "mascot")

QUALITY = 82
METHOD = 6


def main() -> int:
    ap = argparse.ArgumentParser(description="PNG-спрайты маскота -> WebP")
    ap.add_argument("--apply", action="store_true",
                    help="реально пережать и удалить PNG (без флага — только показать)")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("Нужен Pillow:  pip install pillow")
        return 2

    names = sorted(n for n in os.listdir(SPRITES) if n.lower().endswith(".png"))
    if not names:
        print(f"В {SPRITES} нет ни одного .png — похоже, пережатие уже сделано.")
        return 0

    was = now = 0
    for name in names:
        src = os.path.join(SPRITES, name)
        dst = os.path.splitext(src)[0] + ".webp"
        size_png = os.path.getsize(src)
        img = Image.open(src).convert("RGBA")
        if args.apply:
            img.save(dst, "WEBP", quality=QUALITY, method=METHOD)
            size_webp = os.path.getsize(dst)
            os.remove(src)
        else:
            import io
            buf = io.BytesIO()
            img.save(buf, "WEBP", quality=QUALITY, method=METHOD)
            size_webp = buf.tell()
        was += size_png
        now += size_webp
        print(f"  {name:26} {size_png / 1024:6.0f} КБ -> {size_webp / 1024:6.0f} КБ")

    print(f"\nИтого: {was / 1048576:.2f} МБ -> {now / 1048576:.2f} МБ "
          f"(в {was / max(now, 1):.1f} раза меньше)")
    if not args.apply:
        print("Это был холостой прогон. Повтори с --apply, чтобы записать файлы.")
    else:
        print("Готово. ⚠️ Подними ART_VERSION в web/src/config/mascot.js — иначе "
              "браузеры и телефоны продолжат показывать старые картинки из кэша.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
