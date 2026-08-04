"""
build_web_fonts.py — собрать фирменные шрифты для веба из тех же .ttf, что и десктоп.

    python tools/build_web_fonts.py          (нужен `uv sync --extra dev`: fonttools+brotli)

Берёт ПЕРЕМЕННЫЕ начертания из `fonts/` (Syne и DM Sans, лицензия OFL — файл
`fonts/OFL.txt` рядом) и кладёт их в `web/public/fonts/` как woff2. Один файл на
семейство вместо четырёх статических: у переменного шрифта вся ось насыщенности внутри,
а `@font-face` в `web/src/style.css` объявляет диапазон `font-weight`.

━━ ЗАЧЕМ ЭТО ВООБЩЕ ━━
До 3.6 шрифты подключались ссылкой на fonts.googleapis.com, и это давало ТРИ проблемы:
внутри программы (offline-first) шрифта не было вовсе — знак «GB» и заголовки молча
падали на Segoe UI; из РФ Google Fonts отвечает нестабильно, так что тот же эффект ловился
и на сайте, непредсказуемо; и каждый запрос за шрифтом отдавал IP пользователя третьей
стороне за границей (152-ФЗ). Свои файлы снимают все три разом.

⚠️ Кириллицы в обоих семействах НЕТ — её нет и в оригиналах на Google Fonts. Русский текст
всегда рисуется фолбэком (Segoe UI / PT Sans), и это исходный вид продукта, а не регресс.
Скрипт печатает число кириллических глифов именно затем, чтобы это было видно, а не
предполагалось: появится версия с кириллицей — цифра сама об этом скажет.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "fonts")
OUT = os.path.join(ROOT, "web", "public", "fonts")

#(исходный .ttf, имя на выходе). Переменные начертания — по одному на семейство.
PAIRS = [
    ("Syne-VariableFont_wght.ttf", "Syne-Variable.woff2"),
    ("DMSans-VariableFont_opsz,wght.ttf", "DMSans-Variable.woff2"),
]


def main() -> int:
    try:
        from fontTools.ttLib import TTFont
        import brotli  # noqa: F401 — нужен fontTools для сжатия woff2
    except ImportError:
        print("Нужны fonttools и brotli:  uv sync --extra dev")
        return 2

    os.makedirs(OUT, exist_ok=True)
    for src, dst in PAIRS:
        src_path = os.path.join(SRC, src)
        if not os.path.isfile(src_path):
            print(f"нет исходника: {src_path}")
            return 2
        font = TTFont(src_path)
        font.flavor = "woff2"
        out_path = os.path.join(OUT, dst)
        font.save(out_path)
        cmap = font.getBestCmap()
        cyrillic = sum(1 for c in cmap if 0x0400 <= c <= 0x04FF)
        print(f"{dst}: {os.path.getsize(out_path) / 1024:.0f} КБ, "
              f"глифов {len(cmap)}, кириллических {cyrillic}")
    print("Готово. Объявления @font-face — в web/src/style.css (менять их не нужно).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
