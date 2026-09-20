# -*- coding: utf-8 -*-
"""
Разрезать сросшуюся область «средняя перемычка + нижний шеврон».

Для анимации они нужны ПОРОЗНЬ: нижний виден сразу, перемычка появляется после молнии.
В референсе это одна связная фигура, поэтому режем по перешейку — тонкому месту, где они
соприкасаются. Место ищем не на глаз: пробегаем короткие отрезки-кандидаты и берём тот,
что разваливает область ровно НА ДВЕ части и при этом самый короткий (то есть режет по
самому узкому месту, а не поперёк фигуры).
"""
import numpy as np
from trace_ref import mask_of, components, contours, simplify, area

ROOT = r"c:\Users\User\Desktop\The-first-project-Student-Journal--pre-release-2.9\docs\prototypes\ref"
SRC = f"{ROOT}\\ref-b.jpg"

m = mask_of(SRC)
lab, comps = components(m)
by_id = {c['id']: c for c in comps}

hexc = max(comps, key=lambda c: c['pix'] if (c['box'][2] - c['box'][0]) > 200 else 0)
x0, y0, x1, y1 = hexc['box']
R_px = (y1 - y0 + 1) / 2.0
CX, CY = (x0 + x1) / 2.0, (y0 + y1) / 2.0
K = 170.0 / R_px

TARGET = 10                      # «средний + нижний»
sub = (lab == TARGET)
ys, xs = np.nonzero(sub)
bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
print(f"область: x {bx0}..{bx1}  y {by0}..{by1}, пикселей {sub.sum()}")


def cut(mask, p, q, halfwidth=1.6):
    """Стереть полосу вдоль отрезка p→q."""
    out = mask.copy()
    (ax, ay), (bx, by) = p, q
    n = int(max(abs(bx - ax), abs(by - ay)) * 3) + 2
    for i in range(n + 1):
        t = i / n
        cx, cy = ax + (bx - ax) * t, ay + (by - ay) * t
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                if dx * dx + dy * dy <= halfwidth * halfwidth * 4:
                    yy, xx = int(round(cy)) + dy, int(round(cx)) + dx
                    if 0 <= yy < out.shape[0] and 0 <= xx < out.shape[1]:
                        out[yy, xx] = False
    return out


# Кандидаты: горизонтальные и наклонные резы в окрестности перешейка. Перешеек виден по
# профилю: считаем, сколько пикселей области в каждой строке, и берём локальный минимум.
rows = sub.sum(axis=1)
band = [(y, rows[y]) for y in range(by0, by1 + 1) if rows[y] > 0]
print("профиль по строкам (y: ширина):",
      ' '.join(f"{y}:{v}" for y, v in band[::6]))

best = None
for y in range(by0 + 8, by1 - 8):
    if rows[y] == 0:
        continue
    xr = np.nonzero(sub[y])[0]
    # рез по строке: от левого до правого края области в этой строке
    p, q = (int(xr.min()) - 2, y), (int(xr.max()) + 2, y)
    trial = cut(sub, p, q)
    _, cc = components(trial)
    # ⚠️ ОБЕ части обязаны быть ВЕСОМЫМИ. С порогом 250 автомат нашёл "перешеек" у самой
    # макушки и отрезал лоскут в 266 пикселей: формально две области, по сути — ничего.
    big = [c for c in cc if c['pix'] > 1800]
    if len(big) == 2:
        span = xr.max() - xr.min()
        if best is None or span < best[0]:
            best = (span, y, p, q, [c['pix'] for c in big])

print("\nлучший рез:", best)
if not best:
    raise SystemExit("перешеек не найден — резать по строке нельзя, нужен наклонный рез")

_, ycut, p, q, sizes = best
trial = cut(sub, p, q)
lab2, cc = components(trial)
cc = [c for c in cc if c['pix'] > 1800]
cc.sort(key=lambda c: c['box'][1])          # верхняя — перемычка, нижняя — шеврон

names = ['средняя перемычка', 'нижний шеврон']
print(f"\n# рез по строке y={ycut} (в координатах логотипа Y={(ycut-CY)*K:.1f})")
for name, c in zip(names, cc):
    print(f"\n# ── {name}: пикселей {c['pix']}, рамка {c['box']}")
    part = (lab2 == c['id'])
    for loop in contours(part):
        if area(loop) < 40:
            continue
        pts = simplify(loop, 1.1)
        d = []
        for i, (x, y) in enumerate(pts):
            X = (x - 1 - CX) * K
            Y = (y - 1 - CY) * K
            d.append(('M ' if i == 0 else 'L ') + f'{X:.1f},{Y:.1f}')
        print(f'<path d="{" ".join(d)} Z" />')
