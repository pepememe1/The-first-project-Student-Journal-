# -*- coding: utf-8 -*-
"""build_activity_shots.py — снимки активностей для колеса выбора (ActivityWheel.vue).

Берёт исходники из `docs/activity-shots/` и кладёт готовые к вебу файлы в
`web/public/activity/wheel/`. Тот же приём, что у `build_mascot_anim.py` и
`build_web_fonts.py`: исходник живёт в репозитории, в поставку едет обработанный.

🔥 ЗАЧЕМ ВООБЩЕ ОБРАБАТЫВАТЬ, А НЕ ПОЛОЖИТЬ PNG КАК ЕСТЬ. Присланные снимки весят
1.7 МБ и 1.1 МБ. Это не «просто много»: всё, что лежит в `web/public/`, попадает
    • в бандл сайта, который Caddy отдаёт на каждый первый заход;
    • в OTA-бандл Capgo, который КАЖДЫЙ телефон скачивает на каждое обновление;
    • в .exe (сборку и так ужимали с 135 МБ до 49).
Три мегабайта картинок, которые видны только при наведении на сектор колеса, ни одной из
этих цен не стоят. После обработки — десятки килобайт.

⚠️ Ширина режется до 900 px НЕ на глаз: сектор колеса это максимум ~200 CSS-пикселей,
на экране с двойной плотностью — 400. 900 даёт запас на будущее увеличение колеса и всё
равно в разы меньше исходника. Больше — платить трафиком за пиксели, которых не видно.

⚠️ WebP, а не PNG: снимок интерфейса это фотография экрана, и разница в разы. Формат уже
используется в продукте (анимации маскота), поддержан и Chromium, и WebView2, и Android —
новой зависимости у поставки не появляется.

⚠️ Прозрачность СОХРАНЯЕМ, если она есть (у части снимков RGBA): подложить под них белое
значило бы получить белую рамку вокруг тёмного интерфейса.

Запуск:  python -X utf8 tools/build_activity_shots.py [исходная_папка]
"""
from __future__ import annotations

import os
import sys

MAX_WIDTH = 900
QUALITY = 88

#Имена = идентификаторы активностей (`KINDS` в ActivityLauncher.vue). Компонент ищет файл
#строго по id, поэтому список здесь — это ещё и проверка, что снимок назван правильно:
#опечатка в имени иначе просто не подхватилась бы, и сектор молча остался бы со схемой.
KINDS = ("board", "quiz", "contest", "poll", "pulse", "timer")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(ROOT, "docs", "activity-shots")
DST = os.path.join(ROOT, "web", "public", "activity", "wheel")


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("Нужен Pillow:  pip install pillow")
        return 1

    src_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    if not os.path.isdir(src_dir):
        print(f"Нет папки с исходниками: {src_dir}")
        return 1
    os.makedirs(DST, exist_ok=True)

    made, missing = 0, []
    for kind in KINDS:
        src = next((os.path.join(src_dir, f"{kind}{ext}")
                    for ext in (".png", ".jpg", ".jpeg", ".webp")
                    if os.path.isfile(os.path.join(src_dir, f"{kind}{ext}"))), None)
        if src is None:
            missing.append(kind)
            continue

        im = Image.open(src)
        if im.width > MAX_WIDTH:
            h = round(im.height * MAX_WIDTH / im.width)
            im = im.resize((MAX_WIDTH, h), Image.LANCZOS)
        #Прозрачность есть — оставляем RGBA; нет — RGB, иначе к каждому снимку без
        #прозрачности молча приписывался бы лишний канал.
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")

        out = os.path.join(DST, f"{kind}.webp")
        im.save(out, "WEBP", quality=QUALITY, method=6)
        before = os.path.getsize(src) / 1024
        after = os.path.getsize(out) / 1024
        print(f"  {kind:8s} {im.width}x{im.height}  {before:7.0f} КБ -> {after:6.0f} КБ")
        made += 1

    print(f"\nГотово: {made} из {len(KINDS)}")
    if missing:
        #Не ошибка: у активности без снимка колесо рисует схему того же экрана. Но сказать
        #об этом надо — иначе «почему у тайм-бокса не картинка» выясняется догадками.
        print(f"Без снимка (будет схема): {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
