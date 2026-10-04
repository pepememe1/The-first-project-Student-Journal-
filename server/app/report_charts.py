"""Анимированные графики для вечернего письма — GIF, нарисованные Pillow (04.10.2026).

Почему картинкой: Gmail вырезает CSS-анимации (`@keyframes`) и не исполняет ни SVG, ни
скрипты, а анимированный GIF проигрывают все почтовые клиенты. Столбики РАСТУТ один раз и
замирают на последнем кадре (у файла нет признака повтора), числа «досчитываются» вместе
с ними.

⚠️ В картинках только цифры и проценты: подписи по-русски стоят в HTML рядом. Тогда
график не зависит от того, есть ли на машине шрифт с кириллицей, — а на свежем сервере
его может не оказаться.

⚠️ Pillow импортируется внутри функций: модуль зовёт только `nightly_report`, а
локальный сервер программы его не трогает — сборка .exe не обязана тащить Pillow.
"""
from __future__ import annotations

import io

#Рисуем в полтора раза крупнее показа: на экранах с ретиной иначе мыло.
SCALE = 1.5
FRAMES = 16
FRAME_MS = 45
HOLD_MS = 60_000

_FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
          "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf")


def _font(size: int):
    from PIL import ImageFont
    for path in _FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:      # Pillow < 10.1 — шрифт без размера, но цифры читаются
        return ImageFont.load_default()


def _ease(t: float) -> float:
    return 1 - (1 - t) ** 3          #быстрый старт, мягкая посадка


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[k] + (b[k] - a[k]) * t) for k in range(3))


def _save(frames: list) -> bytes:
    from PIL import Image
    base = frames[-1].quantize(colors=128, method=Image.MEDIANCUT)
    pal = [f.quantize(palette=base, dither=Image.NONE) for f in frames]
    durs = [FRAME_MS] * (len(pal) - 1) + [HOLD_MS]
    buf = io.BytesIO()
    #⚠️ Без `loop`: признака повтора в файле нет — графика растёт один раз и стоит.
    pal[0].save(buf, format="GIF", save_all=True, append_images=pal[1:], duration=durs,
                optimize=True, disposal=1)
    return buf.getvalue()


def bars(week: list, color: str, width: int = 600, height: int = 150) -> bytes | None:
    """Столбики недели: `[{date: 'YYYY-MM-DD', n: int}, ...]`, сегодня — последний."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    W, H = int(width * SCALE), int(height * SCALE)
    bg, base_col = (255, 255, 255), _hex(color)
    pale = _mix(base_col, bg, 0.55)
    grid = (232, 238, 240)
    muted = (107, 124, 128)
    #Крупнее «нужного» намеренно: на телефоне график ужимается почти вдвое.
    f_num, f_lbl = _font(int(20 * SCALE)), _font(int(16 * SCALE))
    n = len(week) or 1
    peak = max([w["n"] for w in week] or [0]) or 1
    left, right, top, bottom = int(12 * SCALE), int(12 * SCALE), int(34 * SCALE), int(34 * SCALE)
    slot = (W - left - right) / n
    bw = slot * 0.56
    frames = []
    for f in range(FRAMES + 1):
        t = _ease(f / FRAMES)
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        for g in range(4):
            y = top + (H - top - bottom) * g / 3
            d.line((left, y, W - right, y), fill=grid, width=1)
        for i, w in enumerate(week):
            today = i == n - 1
            x0 = left + slot * i + (slot - bw) / 2
            full = (H - top - bottom) * w["n"] / peak
            h = max(full * t, 3 * SCALE if w["n"] else 2)
            y0 = H - bottom - h
            col = base_col if today else pale
            d.rounded_rectangle((x0, y0, x0 + bw, H - bottom), radius=int(7 * SCALE), fill=col)
            val = str(int(round(w["n"] * t)))
            d.text((x0 + bw / 2, y0 - 5 * SCALE), val, font=f_num,
                   fill=(31, 42, 45) if today else muted, anchor="mb")
            label = w["date"][8:10] + "." + w["date"][5:7]
            d.text((x0 + bw / 2, H - bottom + 9 * SCALE), label, font=f_lbl,
                   fill=(31, 42, 45) if today else muted, anchor="mt")
        frames.append(im)
    return _save(frames)


def gauges(items: list, width: int = 600, height: int = 128) -> bytes | None:
    """Кольца-индикаторы: `[{pct: 0..100, color: '#...'}, ...]`, заполняются по дуге."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    W, H = int(width * SCALE), int(height * SCALE)
    bg, track = (255, 255, 255), (234, 240, 242)
    n = len(items) or 1
    slot = W / n
    r = min(slot, H) * 0.40
    ring = int(13 * SCALE)
    f_big = _font(int(30 * SCALE))
    frames = []
    for f in range(FRAMES + 1):
        t = _ease(f / FRAMES)
        im = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(im)
        for i, it in enumerate(items):
            cx, cy = slot * i + slot / 2, H / 2
            box = (cx - r, cy - r, cx + r, cy + r)
            d.arc(box, 0, 360, fill=track, width=ring)
            pct = max(0.0, min(100.0, float(it.get("pct") or 0)))
            sweep = 360 * pct / 100 * t
            if sweep > 0.5:
                d.arc(box, -90, -90 + sweep, fill=_hex(it.get("color") or "#147C8B"),
                      width=ring)
            d.text((cx, cy), "%d%%" % round(pct * t), font=f_big, fill=(31, 42, 45),
                   anchor="mm")
        frames.append(im)
    return _save(frames)
