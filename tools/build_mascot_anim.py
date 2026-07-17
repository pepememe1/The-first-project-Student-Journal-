# -*- coding: utf-8 -*-
"""
build_mascot_anim.py — конвейер: MP4 с зелёным хромакеем (арт Арины) → прозрачные
анимированные WebP маскота «Вектор» для ВСЕХ платформ (веб/мобилка/десктоп — один формат).

Зачем WebP: анимированный WebP с альфа-каналом играет и в браузерах (веб + Capacitor
WebView на мобилке), и в Qt на десктопе (QMovie/QImageReader supportsAnimation=True).
Значит один файл на состояние покрывает все три платформы — без per-platform вариантов.

Состояния (чат/док Вектора):
  idle     ← «деф (Full)»          покой: уши/хвост шевелятся (дефолт)
  greeting ← «приветствие (Full)»  появление
  thinking ← «думает (Full)»       обдумывает вопрос
  speaking ← «говорит (гол)» ПОВЕРХ покойного тела «деф (тел)»  говорит (рот двигается)

Все состояния кропаются по ОДНОМУ общему bbox → маскот не «прыгает» при смене состояния.

Запуск:  py -3.10 tools/build_mascot_anim.py [out_dir]
Зависимости (dev): av (PyAV), Pillow, numpy — ставить в тот же Python, что и main.py.
"""
import os
import sys
import numpy as np
import av
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "анимации")
FPS = 12
# Целевая высота готового кадра (после общего кропа). Маскот показывается ~200–400px —
# 640 с запасом; прозрачные поля WebP жмёт почти в ноль, размер держим качеством.
TARGET_H = 640
QUALITY = 80
METHOD = 4  # 0..6, компромисс сжатие/скорость (6 слишком медленный на больших кадрах)

# Пауза-покой (сек) в КОНЦЕ цикла: анимация проигрывается, потом маскот «стоит» это
# время, потом цикл повторяется. Нужно ТОЛЬКО покою (idle) — иначе непрерывное движение
# «моргает часто». thinking/speaking — активные состояния, крутятся без пауз (0).
REST_HOLD_S = {"idle": 1.8}

# Число повторов цикла: 0 — бесконечно (idle/thinking/speaking крутятся, пока состояние
# активно), 1 — проиграть ОДИН раз и застыть на последнем кадре. greeting — одноразовое
# «махание»: без loop=1 оно за ~1.5 c успевает начать 2-й проигрыш → «мелькание заново»
# перед переходом в покой. С loop=1 после взмаха замирает, переход idle идёт без рестарта.
LOOP = {"greeting": 1}

# Гашение артефактов рендера Арины: прямоугольники (в координатах ИСХОДНИКА 1536×2048),
# где принудительно ставим альфу в НОЛЬ. thinking: в правом верхнем углу на одном кадре
# вылезают лишние пиксели (артефакт) — персонажа там нет ни в одном кадре, вырезаем угол.
MASK_RECTS = {"thinking": [(1200, 0, 1536, 230)]}  # state -> [(x0,y0,x1,y1), ...]


def key_frame(rgb: np.ndarray) -> np.ndarray:
    """Хромакей яркого жёлто-зелёного (#A9FD00) → RGBA. Мягкий край + деспилл
    (гашение зелёного отлива по контуру). Тигр зелёного не содержит — ключ безопасен."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    greenness = g - np.maximum(r, b)          # насколько G доминирует
    a = np.clip((70 - greenness) / 40.0, 0, 1)  # >70 фон→0, <30 объект→1, между — мягко
    alpha = (a * 255).astype(np.uint8)
    out = rgb.copy()
    spill = greenness > 0
    out[..., 1] = np.where(spill, np.minimum(g, np.maximum(r, b)).astype(np.uint8), rgb[..., 1])
    return np.dstack([out, alpha])


def load_keyed(name: str) -> list[Image.Image]:
    """Декод MP4 → список keyed-RGBA кадров (полный холст 1536×2048)."""
    c = av.open(os.path.join(SRC, name))
    frames = [Image.fromarray(key_frame(fr.to_ndarray(format="rgb24")), "RGBA")
              for fr in c.decode(video=0)]
    c.close()
    return frames


def build_speaking() -> list[Image.Image]:
    """Говорящая голова поверх ПОКОЙНОГО тела: тело — первый кадр «деф (тел)» (статично),
    голова — анимированные кадры «говорит (гол)». Один холст → идеальное совмещение."""
    body = load_keyed("деф (тел).mp4")[0]        # неподвижное тело без головы
    head = load_keyed("говорит (гол).mp4")        # анимированная голова
    out = []
    for h in head:
        frame = body.copy()
        frame.alpha_composite(h)                  # голова поверх шеи (один холст → совпадает)
        out.append(frame)
    return out


def global_bbox(states: dict) -> tuple:
    """Общий bounding box непрозрачных пикселей по ВСЕМ кадрам всех состояний —
    чтобы кроп был одинаковым и маскот не прыгал при переключении."""
    box = None
    for frames in states.values():
        for im in frames:
            bb = im.getchannel("A").getbbox()
            if bb is None:
                continue
            box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]),
                                          max(box[2], bb[2]), max(box[3], bb[3]))
    return box


def finalize(frames: list[Image.Image], box: tuple) -> list[Image.Image]:
    """Кроп по общему box + пропорциональный ресайз до TARGET_H."""
    w = box[2] - box[0]
    h = box[3] - box[1]
    tw = max(1, round(w * TARGET_H / h))
    return [im.crop(box).resize((tw, TARGET_H), Image.LANCZOS) for im in frames]


def save_webp(frames: list[Image.Image], path: str, loop: int = 0) -> int:
    """Сохранить анимированный WebP (равномерная длительность кадра). loop=0 — бесконечно,
    loop=1 — один проигрыш (застыть на последнем кадре). Пауза-покой у idle делается
    ДУБЛИРОВАНИЕМ последнего кадра в main() — надёжнее per-frame-duration (Qt читает его
    нестабильно), а идентичные кадры WebP сжимает почти в ноль (размер не растёт)."""
    frames[0].save(path, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=int(1000 / FPS), loop=loop, disposal=2,
                   lossless=False, quality=QUALITY, method=METHOD)
    return os.path.getsize(path)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "_mascot_anim_out")
    os.makedirs(out_dir, exist_ok=True)

    states = {
        "idle": load_keyed("деф (Full).mp4"),
        "greeting": load_keyed("приветствие (Full).mp4"),
        "thinking": load_keyed("думает (Full).mp4"),
        "speaking": build_speaking(),
    }
    #Гасим артефакты рендера (лишние пиксели) ДО общего кропа — в координатах исходника.
    for name, rects in MASK_RECTS.items():
        for im in states.get(name, []):
            for (x0, y0, x1, y1) in rects:
                im.paste((0, 0, 0, 0), (x0, y0, x1, y1))   #прямоугольник → прозрачный
    box = global_bbox(states)
    print(f"общий bbox: {box}  (кадр {box[2]-box[0]}x{box[3]-box[1]})")

    total = 0
    for name, frames in states.items():
        fin = finalize(frames, box)
        # Пауза-покой: держим последний кадр (поза покоя, без скачка) — цикл получается
        # «движение → стоит → движение». Только для состояний из REST_HOLD_S (idle).
        hold = round(REST_HOLD_S.get(name, 0) * FPS)
        if hold:
            fin = fin + [fin[-1]] * hold
        p = os.path.join(out_dir, f"{name}.webp")
        sz = save_webp(fin, p, loop=LOOP.get(name, 0))
        total += sz
        # превью на шахматке (проверка краёв/совмещения)
        prev = _checker(*fin[len(fin) // 2].size)
        prev.alpha_composite(fin[len(fin) // 2])
        prev.convert("RGB").save(os.path.join(out_dir, f"_{name}_check.png"))
        print(f"  {name:9s} {fin[0].size[0]}x{fin[0].size[1]} {len(fin):2d} кадров  {sz/1024:6.1f} КБ")
    print(f"ИТОГО: {total/1024:.1f} КБ на 4 состояния → {out_dir}")


def _checker(w, h, s=20):
    a = np.zeros((h, w, 3), np.uint8)
    for y in range(0, h, s):
        for x in range(0, w, s):
            a[y:y + s, x:x + s] = 210 if ((x // s + y // s) % 2 == 0) else 160
    return Image.fromarray(a, "RGB").convert("RGBA")


if __name__ == "__main__":
    main()
