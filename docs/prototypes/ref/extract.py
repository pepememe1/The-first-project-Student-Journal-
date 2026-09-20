# -*- coding: utf-8 -*-
"""Извлечь контуры логотипа из ref-b.jpg и напечатать готовые SVG-пути."""
import numpy as np
from trace_ref import mask_of, components, contours, simplify, area

ROOT = r"c:\Users\User\Desktop\The-first-project-Student-Journal--pre-release-2.9\docs\prototypes\ref"
SRC = f"{ROOT}\\ref-b.jpg"

m = mask_of(SRC)                 # с рамкой в 1 пиксель
lab, comps = components(m)

# ── Опорная система: центр большого шестиугольника → (0,0), его R → 170 ────────────
# У остроконечного шестиугольника высота = 2R, ширина = √3·R. Берём высоту: она меряется
# точнее (вершины острые, а боковые грани вертикальные и «плывут» от свечения).
hexc = max(comps, key=lambda c: c['pix'] if (c['box'][2] - c['box'][0]) > 200 else 0)
x0, y0, x1, y1 = hexc['box']
R_px = (y1 - y0 + 1) / 2.0
CX, CY = (x0 + x1) / 2.0, (y0 + y1) / 2.0
K = 170.0 / R_px
print(f"# шестиугольник: рамка x {x0}..{x1} y {y0}..{y1}; R={R_px:.1f}px; масштаб {K:.5f}")
print(f"# ширина/высота = {(x1-x0+1)/(y1-y0+1):.4f} (у правильного остроконечного 0.8660)")

TOL = 1.1        # упрощение: логотип из прямых, поэтому допуск можно держать жёстким


def paths_of(comp, ox, oy, k, prec=1, min_area=25):
    sub = (lab == comp['id'])
    out = []
    for loop in contours(sub):
        if area(loop) < min_area:
            continue
        pts = simplify(loop, TOL)
        if len(pts) < 3:
            continue
        d = []
        for i, (x, y) in enumerate(pts):
            # −1 снимает рамку, добавленную маской
            X = (x - 1 - ox) * k
            Y = (y - 1 - oy) * k
            d.append(('M ' if i == 0 else 'L ') + f'{X:.{prec}f},{Y:.{prec}f}')
        out.append((' '.join(d) + ' Z', len(pts), area(loop)))
    return out


def report(title, comp, ox, oy, k):
    bx = comp['box']
    print(f"\n# ── {title} — исходная рамка x {bx[0]}..{bx[2]} y {bx[1]}..{bx[3]}")
    for d, n, a in sorted(paths_of(comp, ox, oy, k), key=lambda t: -t[2]):
        print(f"#   узлов {n}, площадь {a:.0f}")
        print(f'<path d="{d}" />')


by_id = {c['id']: c for c in comps}

# ── ЗНАК ──────────────────────────────────────────────────────────────────────────
MARK = {
    'большой шестиугольник': 1,
    'верхний шеврон':        2,
    'средний + нижний':     10,
    'узел левый':            9,
    'узел правый':          11,
}
print("\n\n" + "=" * 78)
print("ЗНАК. Координаты от центра шестиугольника, R = 170.")
print("=" * 78)
for title, cid in MARK.items():
    if cid in by_id:
        report(title, by_id[cid], CX, CY, K)

# Центры узлов — они же посадочные места контактов в анимации
for title, cid in (('узел левый', 9), ('узел правый', 11)):
    if cid in by_id:
        b = by_id[cid]['box']
        cx = ((b[0] + b[2]) / 2 - CX) * K
        cy = ((b[1] + b[3]) / 2 - CY) * K
        r = ((b[3] - b[1] + 1) / 2) * K
        ang = np.degrees(np.arctan2(cy, cx)) % 360
        rad = (cx * cx + cy * cy) ** .5
        print(f"# {title}: центр ({cx:.1f}, {cy:.1f}), R хекса {r:.1f}; "
              f"полярно deg={ang:.2f} r={rad:.2f}")

# ── СЛОВО ─────────────────────────────────────────────────────────────────────────
# Базовая линия — низ букв; высота прописной приводится к 100.
LETTERS = [('Y', 6), ('N', 7), ('A', 8), ('P', 3), ('S', 4), ('E', 5)]
tops = [by_id[c]['box'][1] for _, c in LETTERS if c in by_id]
bots = [by_id[c]['box'][3] for _, c in LETTERS if c in by_id]
lefts = [by_id[c]['box'][0] for _, c in LETTERS if c in by_id]
cap = (max(bots) - min(tops) + 1)
KW = 100.0 / cap
OX = min(lefts)
OY = max(bots) + 1            # базовая линия
print("\n\n" + "=" * 78)
print(f"СЛОВО. Высота прописной {cap}px → 100; базовая линия y=0; ширина строки "
      f"{(max(by_id[c]['box'][2] for _, c in LETTERS) - OX + 1) * KW:.1f}")
print("=" * 78)
for name, cid in LETTERS:
    if cid not in by_id:
        continue
    b = by_id[cid]['box']
    print(f"\n# ── {name}: x {(b[0]-OX)*KW:.1f}..{(b[2]-OX)*KW:.1f}")
    ps = sorted(paths_of(by_id[cid], OX, OY, KW), key=lambda t: -t[2])
    inner = ' '.join(d for d, _, _ in ps)
    rule = ' fill-rule="evenodd"' if len(ps) > 1 else ''
    print(f'<path{rule} d="{inner}" />')
