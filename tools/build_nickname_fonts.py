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

⚠️ ПОДРЕЗКА ОБЯЗАТЕЛЬНА (добавлена, когда список вырос с 7 файлов до 19). Шрифт грузится
ради ОДНОЙ строки — имени человека, поэтому греческий, вьетнамский, деванагари и прочее
из исходников — чистый вес на канале. Декоративные Rubik* весят по 400 КБ .ttf, и без
подрезки страница профиля тянула бы мегабайты. Оставляем ровно то, из чего бывают имена
и логины: латиница, кириллица (включая ё/ї/ґ и №), цифры и обычная пунктуация. Осей
вариативных шрифтов подрезка НЕ трогает — Oswald/Tektur/Unbounded остаются переменными.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "fonts", "nickname")
OUT = os.path.join(ROOT, "web", "public", "fonts", "nickname")

#Что оставляем при подрезке. Диапазоны — как у Google Fonts в их подмножествах
#latin + latin-ext(частично) + cyrillic + cyrillic-ext(частично).
UNICODES = (
    "U+0000-00FF,"       # управляющие + латиница + Latin-1 (ä, ö, é — фамилии бывают)
    "U+0131,U+0152-0153,"
    "U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
    "U+2000-206F,"       # типографская пунктуация (тире, кавычки, многоточие)
    "U+2074,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,"
    "U+0400-045F,U+0460-047F,U+048A-04FF,"   # кириллица + расширения (ѣ, ґ, ў, ә…)
    "U+2116,"            # №
    "U+FEFF,U+FFFD"
)

#(исходный .ttf, имя на выходе). Переменные начертания (Unbounded/Comfortaa/Caveat/
#Oswald/Tektur) — по одному файлу с целой осью насыщенности; PT Serif статичный — два
#файла (regular+bold), остальные — по одному начертанию, которое есть у исходника.
PAIRS = [
    #— базовые (3.6.1) ————————————————————————————————————————————————————————
    ("Unbounded.ttf", "Unbounded.woff2"),
    ("Comfortaa.ttf", "Comfortaa.woff2"),
    ("Caveat.ttf", "Caveat.woff2"),
    ("MarckScript.ttf", "MarckScript.woff2"),
    ("PTSerif-Regular.ttf", "PTSerif-Regular.woff2"),
    ("PTSerif-Bold.ttf", "PTSerif-Bold.woff2"),
    ("PTMono.ttf", "PTMono.woff2"),
    #— добавлены в 3.7 по просьбе Влада («добавить ещё шрифтов для ников») ———————
    ("RussoOne.ttf", "RussoOne.woff2"),
    ("Oswald.ttf", "Oswald.woff2"),
    ("Tektur.ttf", "Tektur.woff2"),
    ("Pacifico.ttf", "Pacifico.woff2"),
    ("Lobster.ttf", "Lobster.woff2"),
    ("YesevaOne.ttf", "YesevaOne.woff2"),
    ("RuslanDisplay.ttf", "RuslanDisplay.woff2"),
    ("PressStart2P.ttf", "PressStart2P.woff2"),
    ("RubikGlitch.ttf", "RubikGlitch.woff2"),
    ("RubikMoonrocks.ttf", "RubikMoonrocks.woff2"),
    ("RubikBubbles.ttf", "RubikBubbles.woff2"),
    ("RubikWetPaint.ttf", "RubikWetPaint.woff2"),
]


def main() -> int:
    try:
        from fontTools.ttLib import TTFont
        from fontTools import subset
        import brotli  # noqa: F401 — нужен fontTools для сжатия woff2
    except ImportError:
        print("Нужны fonttools и brotli:  pip install fonttools brotli")
        return 2

    os.makedirs(OUT, exist_ok=True)
    ok = True
    total = 0
    for src, dst in PAIRS:
        src_path = os.path.join(SRC, src)
        if not os.path.isfile(src_path):
            print(f"нет исходника: {src_path}")
            ok = False
            continue
        font = TTFont(src_path)
        #Подрезка ДО сохранения: layout-таблицы чистятся под оставшиеся глифы, оси
        #вариативного шрифта сохраняются как есть (retain_gids не нужен — свой @font-face).
        opts = subset.Options()
        opts.layout_features = ["*"]     # кернинг/лигатуры оставляем, они видны в имени
        opts.name_IDs = ["*"]
        opts.notdef_outline = True
        opts.drop_tables = []
        subsetter = subset.Subsetter(options=opts)
        subsetter.populate(unicodes=subset.parse_unicodes(UNICODES))
        subsetter.subset(font)

        font.flavor = "woff2"
        out_path = os.path.join(OUT, dst)
        font.save(out_path)
        size = os.path.getsize(out_path)
        total += size
        cmap = font.getBestCmap()
        cyrillic = sum(1 for c in cmap if 0x0400 <= c <= 0x04FF)
        mark = "OK" if cyrillic >= 60 else "!! МАЛО КИРИЛЛИЦЫ"
        if cyrillic < 60:
            ok = False
        print(f"{dst:24} {size / 1024:6.0f} КБ  глифов {len(cmap):4}  "
              f"кириллических {cyrillic:4} [{mark}]")
    print(f"Итого {total / 1024:.0f} КБ в {len(PAIRS)} файлах.")
    print("Готово." if ok else "ЕСТЬ ПРОБЛЕМЫ — см. отметки [!!] выше.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
