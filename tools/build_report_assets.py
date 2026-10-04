"""Анимации для вечернего письма: Вектор, радар приманок, пульс-индикаторы (04.10.2026).

    py -3.11 tools/build_report_assets.py

Кладёт GIF в `server/app/report_assets/` — они едут на бой вместе с `server/app` и
вкладываются в письмо (`nightly_report`), а не грузятся с сайта.

━━ ПОЧЕМУ GIF, А НЕ CSS-АНИМАЦИЯ И НЕ WEBP ━━
Письмо читается в Gmail, а Gmail вырезает `@keyframes` и не гарантирует анимированный
WebP. Анимированный GIF проигрывают все почтовые клиенты. CSS-анимации в письме тоже есть,
но как надстройка для Apple Mail/iOS/Thunderbird — без них письмо остаётся целым.

━━ ПОЧЕМУ ФОН ВШИТ В КАДР ━━
У GIF прозрачность однобитная: полупрозрачный край шерсти на чужом фоне превращается в
зубчатую кайму. Поэтому кадр собирается сразу на том цвете, на котором он стоит в письме
(`HERO_BG`), — шов не виден ни в светлой, ни в тёмной теме клиента.

Исходники — ролики Арины `web/public/mascot/anim/*.webp` (тот же арт, что на сайте).
Pillow нужен только здесь, на машине сборки.
"""
from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "web", "public", "mascot", "anim")
OUT = os.path.join(ROOT, "server", "app", "report_assets")

#Цвет «окошка» Вектора в шапке письма — светлая бирюза. Обязан совпадать с
#`nightly_report.HERO_PANEL`, иначе вокруг тигра будет виден прямоугольник.
HERO_BG = (224, 245, 247)
CARD_BG = (255, 255, 255)

#Кадрирование: верхняя часть фигуры (голова, куртка, поднятая лапа) — в квадрате письма
#весь рост в 640 точек превратил бы тигра в спичку.
CROP = (10, 0, 430, 400)
SIZE = (216, 206)            #показываем 144×137 — запас в 1.5 раза на экраны с ретиной


def _mascot(name: str, out_name: str) -> str:
    im = Image.open(os.path.join(SRC, name + ".webp"))
    frames, durs = [], []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        fr = im.convert("RGBA").crop(CROP).resize(SIZE, Image.LANCZOS)
        bg = Image.new("RGBA", SIZE, HERO_BG + (255,))
        bg.alpha_composite(fr)
        frames.append(bg.convert("RGB"))
        durs.append(im.info.get("duration") or 83)
    #ОБЩАЯ палитра на все кадры: своя у каждого кадра дала бы «мерцание» цветов шерсти
    #между кадрами и раздула бы файл.
    base = frames[len(frames) // 2].quantize(colors=255, method=Image.MEDIANCUT)
    pal = [f.quantize(palette=base, dither=Image.NONE) for f in frames]
    path = os.path.join(OUT, out_name)
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=durs, loop=0,
                optimize=True, disposal=1)
    return path


def _radar(path: str, size: int = 96) -> str:
    """Радар приманок: луч обходит круг, на нём вспыхивает «цель»."""
    frames = []
    cx = cy = size // 2
    r = size // 2 - 4
    blip = (cx + int(r * 0.45), cy - int(r * 0.35))
    n = 24
    for i in range(n):
        im = Image.new("RGB", (size, size), CARD_BG)
        d = ImageDraw.Draw(im)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(232, 247, 249), outline=(20, 124, 139),
                  width=2)
        for k in (0.33, 0.66):
            rr = int(r * k)
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(160, 214, 220), width=1)
        d.line((cx - r, cy, cx + r, cy), fill=(190, 226, 230), width=1)
        d.line((cx, cy - r, cx, cy + r), fill=(190, 226, 230), width=1)
        ang = 2 * math.pi * i / n
        #Шлейф луча — несколько секторов с убывающей яркостью.
        for t in range(6):
            a0 = math.degrees(ang) - 90 - (t + 1) * 9
            shade = (20 + t * 30, 124 + t * 18, 139 + t * 16)
            d.pieslice((cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2), a0, a0 + 9, fill=shade)
        x = cx + int(r * math.sin(ang))
        y = cy - int(r * math.cos(ang))
        d.line((cx, cy, x, y), fill=(14, 95, 107), width=3)
        #Цель вспыхивает, когда по ней проходит луч, и гаснет к следующему обороту.
        bang = (math.atan2(blip[0] - cx, cy - blip[1]) + 2 * math.pi) % (2 * math.pi)
        since = (ang - bang) % (2 * math.pi)
        glow = max(0.0, 1 - since / (2 * math.pi) * 1.6)
        if glow > 0:
            rad = 4 + int(4 * glow)
            col = (int(255 - 40 * (1 - glow)), int(80 + 150 * (1 - glow)), int(70 + 160 * (1 - glow)))
            d.ellipse((blip[0] - rad, blip[1] - rad, blip[0] + rad, blip[1] + rad), fill=col)
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(14, 95, 107))
        frames.append(im)
    base = frames[0].quantize(colors=64)
    pal = [f.quantize(palette=base, dither=Image.NONE) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=70, loop=0,
                optimize=True)
    return path


def _pulse(path: str, color: tuple, bg: tuple = CARD_BG, size: int = 44) -> str:
    """Пульсирующий индикатор: точка и расходящееся кольцо («живой» статус)."""
    frames = []
    c = size // 2
    n = 20
    for i in range(n):
        im = Image.new("RGB", (size, size), bg)
        d = ImageDraw.Draw(im)
        t = i / n
        rr = int(7 + (c - 8) * t)
        fade = t
        ring = tuple(int(color[k] * (1 - fade) + bg[k] * fade) for k in range(3))
        d.ellipse((c - rr, c - rr, c + rr, c + rr), outline=ring, width=3)
        d.ellipse((c - 7, c - 7, c + 7, c + 7), fill=color)
        frames.append(im)
    base = frames[0].quantize(colors=32)
    pal = [f.quantize(palette=base, dither=Image.NONE) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=60, loop=0,
                optimize=True)
    return path


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    made = [
        _mascot("greeting", "vector_wave.gif"),
        _mascot("thinking", "vector_think.gif"),
        _radar(os.path.join(OUT, "radar.gif")),
        _pulse(os.path.join(OUT, "pulse_ok.gif"), (31, 157, 107)),
        _pulse(os.path.join(OUT, "pulse_warn.gif"), (214, 137, 16)),
        _pulse(os.path.join(OUT, "pulse_bad.gif"), (192, 57, 43)),
    ]
    for p in made:
        print("%-60s %7d байт" % (os.path.relpath(p, ROOT), os.path.getsize(p)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
