"""
build_pixel_font.py — собрать пиксельный шрифт пасхалок в web/public/fonts/PressStart2P.woff2.

    python tools/build_pixel_font.py

Тот же приём и та же причина, что у tools/build_web_fonts.py и build_nickname_fonts.py:
свой файл, а НЕ ссылка на fonts.googleapis.com. Внутри программы интернета может не
быть вовсе, а каждый запрос к Google отдаёт IP человека третьей стороне (152-ФЗ) — из
CSP боевого Caddy googleapis/gstatic убраны, то есть ссылка там просто не сработает.

⚠️ ПОЧЕМУ ИМЕННО «Press Start 2P», а не что-то более похожее на Undertale. Проверено
запросом к Google Fonts CSS API: у Pixelify Sans, VT323, Silkscreen, Jersey и Handjet
КИРИЛЛИЦЫ НЕТ ВОВСЕ. Пасхалки говорят по-русски, и любой из них молча свалился бы в
monospace — то есть пиксельного вида не было бы совсем, а в коде он бы «был».
Press Start 2P — единственный пиксельный из каталога с кириллицей (178 глифов).

⚠️ Подрезка та же, что у шрифтов никнейма: шрифт грузится ради нескольких коротких
реплик, и греческий с вьетнамским здесь чистый вес на канале.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "fonts", "pixel", "PressStart2P-Regular.ttf")
OUT = os.path.join(ROOT, "web", "public", "fonts", "PressStart2P.woff2")

#Латиница, кириллица, цифры, обычная пунктуация и стрелка-подсказка «▼».
KEEP = ("U+0020-007E,U+00A0,U+0400-045F,U+0490-0491,U+2010-2015,U+2018-201F,"
        "U+2026,U+2116,U+25B2,U+25BC,U+2665")


def main() -> int:
    if not os.path.exists(SRC):
        print(f"нет исходника: {SRC}")
        return 1
    from fontTools import subset
    from fontTools.ttLib import TTFont

    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(SRC, opts)
    subsetter = subset.Subsetter(options=opts)
    subsetter.populate(unicodes=subset.parse_unicodes(KEEP))
    subsetter.subset(font)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    subset.save_font(font, OUT, opts)

    #Печатаем число кириллических глифов не для красоты: ровно на этом уже спотыкались —
    #шрифт «стоял» в CSS, а кириллицы в нём не было, и текст молча рисовался запасным.
    f = TTFont(OUT)
    cmap = set()
    for t in f["cmap"].tables:
        cmap |= set(t.cmap)
    cyr = [c for c in cmap if 0x0400 <= c <= 0x04FF]
    print(f"{OUT}: {os.path.getsize(OUT)} байт, кириллических глифов {len(cyr)}")
    return 0 if cyr else 2


if __name__ == "__main__":
    raise SystemExit(main())
