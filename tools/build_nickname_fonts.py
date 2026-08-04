"""
build_nickname_fonts.py — собрать шрифты стиля никнейма (§5.4, «стиль никнейма») из
fonts/nickname/*.ttf в web/public/fonts/nickname/*.woff2.

    python tools/build_nickname_fonts.py

Тот же приём, что и tools/build_web_fonts.py (см. его докстринг про 152-ФЗ и офлайн):
свои файлы, а не ссылка на fonts.googleapis.com. В ОТЛИЧИЕ от Syne/DM Sans, здесь
кириллица — не опциональный бонус, а САМА СУТЬ фичи (выбор шрифта для отображаемого
имени), поэтому каждый шрифт здесь заведомо проверен на кириллицу (см. таблицу ниже и
`server/tests/test_security_audit.py`-style инвариант — здесь свой: `tests/
test_nickname_fonts.py` проверяет каждый .woff2 на реальный набор кириллических глифов,
а не полагается на то, что скрипт один раз запустили правильно).

Источник — ofl/* в github.com/google/fonts (лицензия OFL, тот же текст, что уже лежит
в fonts/OFL.txt). Скачаны один раз вручную, здесь только конвертация в woff2.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "fonts", "nickname")
OUT = os.path.join(ROOT, "web", "public", "fonts", "nickname")

#(исходный .ttf, имя на выходе). Переменные начертания (Unbounded/Comfortaa/Caveat) —
#по одному файлу с целой осью насыщенности; PT Serif статичный — два файла (regular+bold).
PAIRS = [
    ("Unbounded.ttf", "Unbounded.woff2"),
    ("Comfortaa.ttf", "Comfortaa.woff2"),
    ("Caveat.ttf", "Caveat.woff2"),
    ("MarckScript.ttf", "MarckScript.woff2"),
    ("PTSerif-Regular.ttf", "PTSerif-Regular.woff2"),
    ("PTSerif-Bold.ttf", "PTSerif-Bold.woff2"),
    ("PTMono.ttf", "PTMono.woff2"),
]


def main() -> int:
    try:
        from fontTools.ttLib import TTFont
        import brotli  # noqa: F401 — нужен fontTools для сжатия woff2
    except ImportError:
        print("Нужны fonttools и brotli:  pip install fonttools brotli")
        return 2

    os.makedirs(OUT, exist_ok=True)
    ok = True
    for src, dst in PAIRS:
        src_path = os.path.join(SRC, src)
        if not os.path.isfile(src_path):
            print(f"нет исходника: {src_path}")
            ok = False
            continue
        font = TTFont(src_path)
        font.flavor = "woff2"
        out_path = os.path.join(OUT, dst)
        font.save(out_path)
        cmap = font.getBestCmap()
        cyrillic = sum(1 for c in cmap if 0x0400 <= c <= 0x04FF)
        mark = "OK" if cyrillic >= 60 else "!! МАЛО КИРИЛЛИЦЫ"
        if cyrillic < 60:
            ok = False
        print(f"{dst}: {os.path.getsize(out_path) / 1024:.0f} КБ, "
              f"глифов {len(cmap)}, кириллических {cyrillic} [{mark}]")
    print("Готово." if ok else "ЕСТЬ ПРОБЛЕМЫ — см. отметки [!!] выше.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
