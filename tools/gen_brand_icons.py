"""
gen_brand_icons.py — растровые иконки из ФИРМЕННОГО ЗНАКА (двухцветный гексагон «GB»).

Один источник — тот же знак, что BrandLogo.vue (ядро делится по диагонали на два оттенка
акцента). Отсюда генерируются ВСЕ растровые иконки продукта, чтобы бренд был единым:
  • PWA/веб        web/public/icons/icon-192, icon-512, icon-maskable-512;
  • Android APK    mipmap-*/ic_launcher.png + ic_launcher_round.png + ic_launcher_foreground.png;
  • Десктоп .exe   icon.ico (мультиразмер) + icon.png.

Рендерим в 4× и уменьшаем — так края гексагона и «GB» получаются гладкими без SVG-движка.
Цвета — дефолт ВСГУТУ (растровую иконку под тему не перекрасишь, в отличие от фавикона).

    python tools/gen_brand_icons.py            # отчёт, файлы не трогаем
    python tools/gen_brand_icons.py --apply    # записать
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#DM Sans Black, а не Syne: у Syne глиф «B» геометричный и на иконке читается как «E».
#DM Sans — тоже шрифт бренда (основной текстовый), и «GB» в нём однозначно читаемы.
FONT = os.path.join(ROOT, "fonts", "DMSans-Black.ttf")

#Дефолтная палитра ВСГУТУ (совпадает с favicon.svg и BrandLogo при теме по умолчанию).
ACCENT = (20, 124, 139)     # #147C8B
ACCENT2 = (15, 93, 104)     # #0f5d68
WHITE = (255, 255, 255)

SS = 4                       #суперсэмплинг: рендерим в SS раз крупнее, потом уменьшаем


def _hex_points(cx, cy, r):
    """Вершины гексагона с ОСТРЫМ верхом (как в знаке): верх, и по часовой."""
    #Пропорции берём из BrandLogo (viewBox 200, вершины OUTER) — слегка «пухлый» гексагон.
    #Нормируем к радиусу r вокруг центра.
    pts = [(100, 7), (180.5, 53.5), (180.5, 146.5), (100, 193), (19.5, 146.5), (19.5, 53.5)]
    out = []
    for x, y in pts:
        out.append((cx + (x - 100) / 93.0 * r, cy + (y - 100) / 93.0 * r))
    return out


def render(px, pad=0.06, bg=None, ring=True):
    """Иконка стороной px. pad — доля пустого поля вокруг (для maskable больше). bg —
    цвет фона (None = прозрачный). ring — тонкая светлая обводка гексагона для чёткости."""
    S = px * SS
    img = Image.new("RGBA", (S, S), (bg + (255,)) if bg else (0, 0, 0, 0))
    r = S * (0.5 - pad)
    cx = cy = S / 2
    hexp = _hex_points(cx, cy, r)

    #Маска гексагона.
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(hexp, fill=255)

    #Двухцветная заливка: база accent2, поверх треугольник accent (там, где x+y < S).
    fill = Image.new("RGBA", (S, S), ACCENT2 + (255,))
    tri = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(tri).polygon([(0, 0), (S, 0), (0, S)], fill=ACCENT + (255,))
    fill = Image.alpha_composite(fill, tri)

    #Кладём заливку через маску гексагона.
    img.paste(fill, (0, 0), mask)

    d = ImageDraw.Draw(img)
    if ring:
        #Тонкая полупрозрачная белая обводка — знак не сливается с тёмным фоном.
        d.line(hexp + [hexp[0]], fill=(255, 255, 255, 90), width=max(2, int(S * 0.012)),
               joint="curve")

    #«GB» по центру. Буквы рисуем ПОРАЗДЕЛЬНО с зазором: так они не слипаются и читаются
    #даже на 16px. Размер — доля радиуса (0.80 подобрано под гексагон, как в BrandLogo).
    font = ImageFont.truetype(FONT, int(r * 0.80))
    gap = int(r * 0.06)
    bg_ = d.textbbox((0, 0), "G", font=font)
    bb_ = d.textbbox((0, 0), "B", font=font)
    gw, bw = bg_[2] - bg_[0], bb_[2] - bb_[0]
    total = gw + gap + bw
    x0 = cx - total / 2
    hh = max(bg_[3] - bg_[1], bb_[3] - bb_[1])
    ty = cy - hh / 2 - min(bg_[1], bb_[1])
    d.text((x0 - bg_[0], ty), "G", font=font, fill=WHITE + (255,))
    d.text((x0 + gw + gap - bb_[0], ty), "B", font=font, fill=WHITE + (255,))

    return img.resize((px, px), Image.LANCZOS)


#Что генерируем: (относительный путь, размер, pad, bg, ring)
def _targets():
    A = "web/android/app/src/main/res"
    mip = {"ldpi": 36, "mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    t = []
    #PWA / веб: знак заполняет почти всё, прозрачный фон.
    t.append(("web/public/icons/icon-192.png", 192, 0.06, None, True))
    t.append(("web/public/icons/icon-512.png", 512, 0.06, None, True))
    #maskable: система может обрезать углы/сделать круг — даём БОЛЬШОЙ отступ и НЕПРОЗРАЧНЫЙ
    #фон, иначе на части лаунчеров знак срежется или повиснет на пустоте.
    t.append(("web/public/icons/icon-maskable-512.png", 512, 0.22, (10, 40, 46), True))
    #Android legacy mipmaps: квадрат и круг, знак — силуэт (прозрачный фон).
    for dens, sz in mip.items():
        t.append((f"{A}/mipmap-{dens}/ic_launcher.png", sz, 0.05, None, True))
        t.append((f"{A}/mipmap-{dens}/ic_launcher_round.png", sz, 0.05, None, True))
    #Adaptive foreground: знак в безопасной зоне (система инсетит 16.7% и кропит по форме),
    #поэтому доп. отступ, прозрачный фон (фон рисует отдельный слой).
    t.append((f"{A}/mipmap-xxxhdpi/ic_launcher_foreground.png", 432, 0.26, None, False))
    t.append((f"{A}/mipmap-xxhdpi/ic_launcher_foreground.png", 324, 0.26, None, False))
    t.append((f"{A}/mipmap-xhdpi/ic_launcher_foreground.png", 216, 0.26, None, False))
    t.append((f"{A}/mipmap-hdpi/ic_launcher_foreground.png", 162, 0.26, None, False))
    t.append((f"{A}/mipmap-mdpi/ic_launcher_foreground.png", 108, 0.26, None, False))
    t.append((f"{A}/mipmap-ldpi/ic_launcher_foreground.png", 81, 0.26, None, False))
    #Десктоп png (превью на сайте/в About).
    t.append(("icon.png", 256, 0.05, None, True))
    return t


def main() -> int:
    ap = argparse.ArgumentParser(description="Генерация иконок из фирменного знака")
    ap.add_argument("--apply", action="store_true", help="записать (без флага — отчёт)")
    args = ap.parse_args()

    if not os.path.exists(FONT):
        print(f"Шрифт не найден: {FONT}")
        return 1

    targets = _targets()
    print("=" * 66)
    print("ГЕНЕРАЦИЯ ИКОНОК ИЗ ФИРМЕННОГО ЗНАКА (гексагон GB)")
    print("=" * 66)
    for rel, sz, pad, bg, ring in targets:
        path = os.path.join(ROOT, rel)
        if args.apply:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            render(sz, pad, bg, ring).save(path)
        print(f"  {'записан' if args.apply else 'к записи'}: {rel}  ({sz}px)")

    #icon.ico — мультиразмерный (Windows берёт нужный размер сам).
    ico_path = os.path.join(ROOT, "icon.ico")
    if args.apply:
        base = render(256, 0.05, None, True)
        base.save(ico_path, format="ICO",
                  sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"  {'записан' if args.apply else 'к записи'}: icon.ico  (16..256, мультиразмер)")

    if not args.apply:
        print("\nХОЛОСТОЙ ПРОГОН: файлы не изменены. Записать — с флагом --apply.")
    else:
        print("\nГОТОВО. Веб-иконки — пересобрать npm run build; APK — новая сборка; "
              "exe — пересборка (icon.ico уже обновлён).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
