# -*- coding: utf-8 -*-
"""
trace_ref.py — обводка референсов логотипа Synapse в SVG-контуры.

Почему обводим кодом, а не рисуем по описанию: две попытки нарисовать знак «по мотивам»
дали не тот знак. Пиксели не спорят — из них получается ровно та форма, что на картинке.

Как это работает:
  1. маска = насыщенный и достаточно яркий пиксель. Молния БЕЛАЯ (низкая насыщенность),
     поэтому тем же порогом она отсекается — иначе она слиплась бы с «S»;
  2. marching squares по маске даёт замкнутые контуры (и внешние, и дырки);
  3. Дуглас–Пекер выпрямляет их: логотип состоит из прямых, поэтому упрощение сводит
     тысячи пикселей к настоящим углам многоугольника;
  4. координаты переводятся в удобную систему и печатаются как SVG `d`.
"""
import sys
import numpy as np
from PIL import Image

# Кейсы marching squares. Углы: tl=8, tr=4, br=2, bl=1.
# Рёбра: T (верх), R (право), B (низ), L (лево) — середины сторон клетки.
_SEG = {
    1:  [('L', 'B')], 2:  [('B', 'R')], 3:  [('L', 'R')],
    4:  [('R', 'T')], 5:  [('L', 'T'), ('R', 'B')], 6:  [('B', 'T')],
    7:  [('L', 'T')], 8:  [('T', 'L')], 9:  [('T', 'B')],
    10: [('T', 'R'), ('B', 'L')], 11: [('T', 'R')], 12: [('R', 'L')],
    13: [('R', 'B')], 14: [('B', 'L')],
}


def _edge_point(x, y, e):
    """Середина стороны клетки (x,y) в удвоенных целых координатах — чтобы ключи склеивались."""
    if e == 'T': return (2 * x + 1, 2 * y)
    if e == 'B': return (2 * x + 1, 2 * y + 2)
    if e == 'L': return (2 * x, 2 * y + 1)
    return (2 * x + 2, 2 * y + 1)          # 'R'


def contours(mask):
    """Замкнутые контуры маски. Возвращает список списков точек (в пикселях)."""
    m = mask.astype(np.uint8)
    case = (m[:-1, :-1] << 3) | (m[:-1, 1:] << 2) | (m[1:, 1:] << 1) | m[1:, :-1]
    ys, xs = np.nonzero((case != 0) & (case != 15))

    nxt = {}
    for y, x in zip(ys.tolist(), xs.tolist()):
        for a, b in _SEG[int(case[y, x])]:
            nxt.setdefault(_edge_point(x, y, a), []).append(_edge_point(x, y, b))

    loops = []
    used = set()
    for start in list(nxt):
        if start in used or not nxt.get(start):
            continue
        loop, cur = [], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            nx = outs.pop()
            used.add(cur)
            loop.append((cur[0] / 2.0, cur[1] / 2.0))
            cur = nx
            if cur == start:
                break
            if len(loop) > 4_000_000:
                break
        if len(loop) >= 8:
            loops.append(loop)
    return loops


def _perp(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** .5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** .5


def simplify(pts, tol):
    """Дуглас–Пекер, итеративно (рекурсия на тысячах точек упирается в предел стека)."""
    if len(pts) < 3:
        return pts[:]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        worst, wi = -1.0, -1
        for k in range(i + 1, j):
            d = _perp(pts[k], pts[i], pts[j])
            if d > worst:
                worst, wi = d, k
        if worst > tol:
            keep[wi] = True
            stack.append((i, wi))
            stack.append((wi, j))
    return [p for p, k in zip(pts, keep) if k]


def area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def mask_of(path, vmin=110, smin=120, box=None):
    hsv = np.asarray(Image.open(path).convert("HSV")).astype(np.int16)
    S, V = hsv[..., 1], hsv[..., 2]
    m = (V > vmin) & (S > smin)
    if box:
        x0, y0, x1, y1 = box
        out = np.zeros_like(m)
        out[y0:y1, x0:x1] = m[y0:y1, x0:x1]
        m = out
    # Рамка нулей, иначе контуры фигур, касающихся края, не замкнутся.
    p = np.zeros((m.shape[0] + 2, m.shape[1] + 2), bool)
    p[1:-1, 1:-1] = m
    return p


def components(mask):
    """Связные области (4-связность), итеративной заливкой."""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    cur = 0
    out = []
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if lab[sy, sx]:
            continue
        cur += 1
        stack = [(sy, sx)]
        lab[sy, sx] = cur
        pix = 0
        miny = maxy = sy
        minx = maxx = sx
        while stack:
            y, x = stack.pop()
            pix += 1
            if y < miny: miny = y
            if y > maxy: maxy = y
            if x < minx: minx = x
            if x > maxx: maxx = x
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
        out.append({'id': cur, 'pix': pix, 'box': (minx, miny, maxx, maxy)})
    return lab, out


def to_svg(loops, ox, oy, scale, tol_note='', prec=2):
    """Контуры → строка `d`. Начало координат и масштаб задаёт вызывающий."""
    parts = []
    for pts in loops:
        d = []
        for i, (x, y) in enumerate(pts):
            X = (x - ox) * scale
            Y = (y - oy) * scale
            d.append(('M ' if i == 0 else 'L ') + f'{X:.{prec}f},{Y:.{prec}f}')
        parts.append(' '.join(d) + ' Z')
    return ' '.join(parts)


if __name__ == '__main__':
    ROOT = r"c:\Users\User\Desktop\The-first-project-Student-Journal--pre-release-2.9\docs\prototypes\ref"
    name = sys.argv[1] if len(sys.argv) > 1 else 'ref-a'
    m = mask_of(f"{ROOT}\\{name}.jpg")
    lab, comps = components(m)
    comps.sort(key=lambda c: -c['pix'])
    print(f"{name}: связных областей {len(comps)}")
    for c in comps[:24]:
        x0, y0, x1, y1 = c['box']
        print(f"  #{c['id']:3d} пикселей {c['pix']:7d}  x {x0:4d}..{x1:4d}  y {y0:4d}..{y1:4d}"
              f"  ({x1-x0+1}×{y1-y0+1})")
