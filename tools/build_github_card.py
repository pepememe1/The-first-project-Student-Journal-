# -*- coding: utf-8 -*-
"""build_github_card.py — карточка репозитория для GitHub (Open Graph, 1280×640).

━━ ЗАЧЕМ КОДОМ, А НЕ В РЕДАКТОРЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ровно та же причина, что у превью виджетов (`tools/build_widget_previews.py`):
картинка, нарисованная руками один раз, устаревает МОЛЧА. Сменится название, знак,
цвет темы или список платформ — и карточка продолжит показывать прошлогоднюю правду
всем, кто открыл репозиторий. Собранная скриптом пересобирается за секунду.

━━ РАЗМЕР И ПОЛЯ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1280×640 — формат самого GitHub (его шаблон
`repository-open-graph-template.png`). ⚠️ Он же требует ОТСТУП 40 pt по краю: карточка
показывается в разных местах с разной обрезкой (лента, предпросмотр ссылки в Telegram,
превью в поиске), и всё, что ближе к краю, однажды окажется срезанным. Здесь отступ
взят с запасом — 80 px, как на самом шаблоне.

━━ ШРИФТЫ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ ФИРМЕННЫЕ Syne и DM Sans ЗДЕСЬ НЕ ГОДЯТСЯ, и это проверено, а не предположено: ни
в одном из них НЕТ КИРИЛЛИЦЫ (`fontTools` → `getBestCmap`, ни одной буквы из
«Электронный журнал»). Взяли бы их — надпись собралась бы из пустых прямоугольников
либо молча подменилась системным шрифтом. Поэтому берём Unbounded и Oswald из
`fonts/nickname/` — они лежат в репозитории под OFL и кириллицу покрывают.

⚠️ Системный Segoe UI не берём СОЗНАТЕЛЬНО, хотя он и подошёл бы по рисунку: у
продукта впереди заявка в реестр Минцифры, и «шрифт Microsoft» в исходниках сборки —
лишний вопрос там, где его можно не создавать.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "fonts" / "nickname"
OUT = ROOT / "docs" / "github-card.png"

W, H = 1280, 640
SAFE = 80                      # поле, за которое ничего важного не заходит

# Палитра — та же, что у продукта (`web/src/theme`, дефолт ВСГУТУ).
BG = (14, 26, 33)
TEAL = (20, 124, 139)
TEAL_DARK = (15, 93, 104)
TEAL_LIGHT = (61, 196, 214)
TEXT = (240, 247, 249)
TEXT_2 = (176, 199, 207)
TEXT_3 = (118, 145, 155)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS / name
    if not path.exists():
        raise SystemExit(
            f"нет шрифта {path}. Он лежит в репозитории (fonts/nickname) — если пропал, "
            "карточку собирать нечем, и молча подставлять системный нельзя: "
            "у половины из них другая кириллица или её нет вовсе.")
    return ImageFont.truetype(str(path), size)


# ─────────────────────────────────────────────────────────────────────────────────
# Фон
# ─────────────────────────────────────────────────────────────────────────────────

def hex_points(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """Шестиугольник ОСТРИЁМ ВВЕРХ — тот же разворот, что у знака и у фона продукта."""
    return [(cx + r * math.sin(math.pi / 3 * i), cy - r * math.cos(math.pi / 3 * i))
            for i in range(6)]


def draw_background(img: Image.Image) -> None:
    """Тёмный фон + сетка гексагонов + тёплое свечение справа, под маскотом."""
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=BG)

    # Сетка гексагонов — узнаваемый фон продукта (`HexBackground.vue`). Держим ЕДВА
    # заметной: она обязана читаться как фактура, а не спорить с текстом.
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    r = 46
    step_x = r * math.sqrt(3)
    step_y = r * 1.5
    row = 0
    y = -r
    while y < H + r:
        x = -step_x if row % 2 == 0 else -step_x / 2
        while x < W + step_x:
            gd.polygon(hex_points(x, y, r), outline=(*TEAL, 34), width=2)
            x += step_x
        y += step_y
        row += 1
    img.alpha_composite(grid)

    # Свечение за маскотом: тёплое пятно, которое отделяет его от фона без рамки.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([700, 40, 1290, 600], fill=(*TEAL, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img.alpha_composite(glow)


# ─────────────────────────────────────────────────────────────────────────────────
# Знак GB
# ─────────────────────────────────────────────────────────────────────────────────

def draw_mark(img: Image.Image, cx: int, cy: int, r: int) -> None:
    """Фирменный знак: двухцветный гексагон с буквами GB (см. web/public/favicon.svg).

    Рисуем ЕГО ЖЕ, а не вставляем готовую png-иконку: иконку пришлось бы растягивать,
    а знак здесь самый мелкий элемент карточки — ему нужна чёткая кромка.

    ⚠️ Тёмная половина накладывается ЧЕРЕЗ ПЕРЕСЕЧЕНИЕ ДВУХ МАСОК (гексагон × нижний
    треугольник). Первая версия складывала их «на глаз» через composite и выдавала
    вместо знака бесформенное пятно — на карточке это видно сразу, но такую же ошибку
    в мелком элементе легко пропустить, поэтому маски здесь считаются явно.
    """
    scale = 4                                   # рисуем вчетверо крупнее и ужимаем — сглаживание
    size = r * 2 * scale + 8
    c = size / 2
    pts = hex_points(c, c, r * scale)

    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    #⚠️ Светлая кромка ОБЯЗАТЕЛЬНА, а не украшение: фирменный бирюзовый на тёмном фоне
    #продукта отличается от него на глаз слабо, и знак «частично сливался» (замечание
    #Ярослава). Обводка возвращает силуэт, не трогая сам цвет знака.
    ImageDraw.Draw(tile).polygon(pts, fill=TEAL,
                                 outline=(*TEAL_LIGHT, 255), width=scale * 2)

    hex_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(hex_mask).polygon(pts, fill=255)
    diag_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(diag_mask).polygon([(0, size), (size, 0), (size, size)], fill=255)
    lower_right = ImageChops.darker(hex_mask, diag_mask)
    tile.paste(Image.new("RGBA", (size, size), (*TEAL_DARK, 255)), (0, 0), lower_right)

    #⚠️ Буквы РАВНО НАСТОЛЬКО мелкие, чтобы между ними и скошенными гранями осталось
    #поле. При 0.74 они упирались в грани, и на карточке гексагон читался квадратом:
    #в мелком размере силуэт держат именно срезанные углы, а не сама форма.
    f = font("Unbounded.ttf", int(r * scale * 0.52))
    ImageDraw.Draw(tile).text((c, c + r * scale * 0.06), "GB", font=f,
                              fill=(255, 255, 255), anchor="mm")

    tile = tile.resize((r * 2 + 2, r * 2 + 2), Image.LANCZOS)
    img.alpha_composite(tile, (cx - r, cy - r))


# ─────────────────────────────────────────────────────────────────────────────────
# Плашки платформ
# ─────────────────────────────────────────────────────────────────────────────────

def draw_chip(d: ImageDraw.ImageDraw, x: int, y: int, text: str,
              f: ImageFont.FreeTypeFont) -> int:
    """Одна плашка. Возвращает x, с которого начинается следующая."""
    pad_x, pad_y = 18, 10
    tw = d.textlength(text, font=f)
    th = f.size
    w = int(tw) + pad_x * 2
    h = th + pad_y * 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                        outline=(*TEAL_LIGHT, 150), width=2)
    d.text((x + pad_x, y + pad_y - 2), text, font=f, fill=TEXT_2)
    return x + w + 12


# ─────────────────────────────────────────────────────────────────────────────────
# Сборка
# ─────────────────────────────────────────────────────────────────────────────────

def build(head_path: Path) -> Image.Image:
    img = Image.new("RGBA", (W, H), BG)
    draw_background(img)

    # ── Маскот справа ────────────────────────────────────────────────────────────
    head = Image.open(head_path).convert("RGBA")
    head = head.crop(head.getchannel("A").getbbox())      # убираем прозрачные поля
    target_w = 430
    head = head.resize((target_w, round(target_w * head.height / head.width)), Image.LANCZOS)
    #⚠️ Ровно по границе поля, без «плюс десять на глаз»: кончики ушей — самая
    #выступающая часть рисунка, и при обрезке предпросмотра срезает именно их.
    hx = W - SAFE - target_w
    hy = (H - head.height) // 2
    # Мягкая тень под мордой: без неё она «наклеена», а не лежит на фоне.
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", head.size, (0, 0, 0, 120)), (hx + 6, hy + 14),
                 head.getchannel("A"))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    img.alpha_composite(head, (hx, hy))

    d = ImageDraw.Draw(img)

    # ── Левая колонка ────────────────────────────────────────────────────────────
    # Состав намеренно КОРОТКИЙ: знак и команда, имя, одна поясняющая строка, один
    # ряд технологий. Требование Ярослава дословно — «указан стек, значок GB, вектора
    # бошка, надпись Synapse и GradeBookAI, но не выглядеть перегруженной». Всё, что
    # сюда просилось дальше (версии, ссылки, число тестов), оставлено за бортом
    # сознательно: карточку смотрят полторы секунды, и пятый блок съедает первые четыре.
    x = SAFE + 30
    limit = 740                                  # правее начинается маскот

    draw_mark(img, x + 34, 150, 34)
    f_team = font("Oswald.ttf", 28)
    d.text((x + 86, 150), "SYNAPSE", font=f_team, fill=TEXT_2, anchor="lm")

    # Заголовок вписываем ПО ЗАМЕРУ, а не «на глаз»: шрифт может смениться, и
    # прибитый кегль однажды уедет под маскота молча.
    size = 78
    while size > 40:
        f_title = font("Unbounded.ttf", size)
        if d.textlength("GradeBookAI", font=f_title) <= limit - x:
            break
        size -= 2
    d.text((x, 210), "GradeBookAI", font=f_title, fill=TEXT)

    d.rectangle([x, 210 + size + 26, x + 88, 210 + size + 31], fill=TEAL_LIGHT)

    f_sub = font("Oswald.ttf", 30)
    d.text((x, 210 + size + 56), "Электронный журнал успеваемости",
           font=f_sub, fill=TEXT_2)
    f_small = font("Oswald.ttf", 24)
    d.text((x, 210 + size + 96), "Desktop · Веб · Android · offline-first",
           font=f_small, fill=TEXT_3)

    # Стек — одним рядом и только то, на чём продукт действительно стоит.
    f_chip = font("Oswald.ttf", 22)
    cx = x
    for chip in ("Vue 3", "FastAPI", "Python", "SQLCipher", "Capacitor"):
        cx = draw_chip(d, cx, H - SAFE - 84, chip, f_chip)

    return img.convert("RGB")


def main() -> None:
    head = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "emotions" / "эмоции" / "деф+деф.png"
    if not head.exists():
        raise SystemExit(f"нет исходника морды: {head}")
    img = build(head)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"готово: {OUT} ({img.size[0]}×{img.size[1]}, {OUT.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    main()
