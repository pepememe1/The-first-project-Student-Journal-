"""Иконки кнопок сервера для рабочего стола (27.10.2026).

Рисуются Pillow в 1024 px и ужимаются: тонкая линия на 16 px исчезла бы, поэтому все
штрихи толстые. Запуск: py -3.11 make_icons.py <папка>.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 1024
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
WHITE = (255, 255, 255, 255)


def tile(top, bottom):
    """Скруглённый квадрат с вертикальным градиентом и мягким бликом сверху."""
    grad = Image.new("RGBA", (S, S))
    px = grad.load()
    for y in range(S):
        t = y / (S - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)) + (255,)
        for x in range(S):
            px[x, y] = c
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    #Блик — затухающий к середине, а не полоса с резким краем.
    shine = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sp = shine.load()
    for y in range(S // 2):
        a = round(46 * (1 - y / (S // 2)) ** 2)
        for x in range(S):
            sp[x, y] = (255, 255, 255, a)
    out.alpha_composite(Image.composite(shine, Image.new("RGBA", (S, S)), mask))
    return out


def stroke_line(d, a, b, w, fill=WHITE):
    d.line((a, b), fill=fill, width=w)
    for x, y in (a, b):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)


def stroke_arc(d, c, r, start, end, w, fill=WHITE, caps=(True, True)):
    box = (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    d.arc(box, start, end, fill=fill, width=w)
    for ang, cap in zip((start, end), caps, strict=True):
        if not cap:
            continue
        x, y = point(c, r - w / 2, ang)
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)


def point(c, r, ang):
    a = math.radians(ang)
    return c[0] + r * math.cos(a), c[1] + r * math.sin(a)


def arrowhead(d, c, r, ang, clockwise, w, fill=WHITE):
    """Наконечник на дуге: смотрит по касательной в сторону движения."""
    a = math.radians(ang)
    mid = r - w / 2
    p = (c[0] + mid * math.cos(a), c[1] + mid * math.sin(a))
    tx, ty = -math.sin(a), math.cos(a)          # по часовой (ось y вниз)
    if not clockwise:
        tx, ty = -tx, -ty
    nx, ny = math.cos(a), math.sin(a)
    size = w * 1.45
    tip = (p[0] + tx * size, p[1] + ty * size)
    d.polygon([tip, (p[0] + nx * size, p[1] + ny * size),
               (p[0] - nx * size, p[1] - ny * size)], fill=fill)


def power():
    im = tile((236, 84, 84), (176, 32, 40))
    d = ImageDraw.Draw(im)
    c, w = (512, 560), 92
    stroke_arc(d, c, 270, -55, 235, w)
    stroke_line(d, (512, 215), (512, 520), w)
    return im


def restart():
    im = tile((34, 166, 179), (11, 79, 89))
    d = ImageDraw.Draw(im)
    c, r, w = (512, 540), 280, 92
    stroke_arc(d, c, r, -60, 230, w, caps=(True, False))
    arrowhead(d, c, r, 230, True, w)
    return im


def rollback():
    im = tile((248, 170, 40), (196, 104, 8))
    d = ImageDraw.Draw(im)
    c, r, w = (512, 520), 290, 84
    stroke_arc(d, c, r, 215, 515, w, caps=(False, True))
    arrowhead(d, c, r, 215, False, w)
    stroke_line(d, c, (512, 345), 70)
    stroke_line(d, c, (640, 600), 70)
    return im


def console():
    im = tile((40, 52, 78), (12, 18, 32))
    d = ImageDraw.Draw(im)
    green = (110, 231, 160, 255)
    w = 96
    stroke_line(d, (270, 330), (470, 512), w, green)
    stroke_line(d, (470, 512), (270, 694), w, green)
    stroke_line(d, (560, 700), (760, 700), w)
    return im


def guide():
    im = tile((139, 92, 246), (91, 33, 182))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 720)
    except OSError:
        font = ImageFont.load_default()
    d.text((512, 540), "?", font=font, fill=WHITE, anchor="mm")
    return im


def save(im, path):
    base = im.resize((256, 256), Image.LANCZOS)
    base.save(path, format="ICO", sizes=SIZES)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("hard_switch", power), ("restart", restart), ("rollback", rollback),
                     ("console", console), ("guide", guide)):
        im = fn()
        save(im, out / ("%s.ico" % name))
        im.resize((256, 256), Image.LANCZOS).save(out / ("%s.png" % name))
    print("иконки:", out)


if __name__ == "__main__":
    main()
