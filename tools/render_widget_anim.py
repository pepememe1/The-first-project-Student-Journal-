"""Анимированный предпросмотр виджета: стрелка «идёт сейчас», смена пары, обратный
отсчёт на маленьком виджете, прокрутка списка.

⚠️ Это МОКАП из тех же чисел, что заданы в XML и провайдере, а НЕ запись живого
виджета: эмулятора на машине нет. Расхождение возможно в мелочах отрисовки шрифта
системой, но размеры, кегли, цвета и логика отбора строк здесь ровно те же.

⚠️ Файл править ТОЛЬКО через редактор, понимающий UTF-8. Однажды его пропустили через
`Get-Content | Set-Content` в Windows PowerShell 5.1 — тот читает UTF-8 как ANSI, и
весь русский текст превратился в мохибейк, который уже не восстанавливался обратной
перекодировкой (часть байт теряется безвозвратно). Пришлось переписывать целиком.
"""
import sys
import pathlib
from PIL import Image, ImageDraw, ImageFont

SCALE = 3.0                      # xxhdpi


def dp(v):
    return int(round(v * SCALE))


def sp(v):
    return int(round(v * SCALE))


FONTS = pathlib.Path("C:/Windows/Fonts")
_FONT_CACHE = {}


def font(px, bold=False):
    key = (px, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    names = ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for n in names:
        p = FONTS / n
        if p.exists():
            _FONT_CACHE[key] = ImageFont.truetype(str(p), px)
            return _FONT_CACHE[key]
    _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


LIGHT = dict(bg="#ffffff", border="#e2e8f0", row="#f1f5f9", row_now="#d9f0ef",
             text="#0f172a", text2="#64748b", text3="#475569", past="#94a3b8",
             accent="#008080", accent_soft="#d9f0ef", page="#e8edf2", cap="#64748b")
DARK = dict(bg="#12161c", border="#232a33", row="#1b2129", row_now="#123536",
            text="#e8eef6", text2="#8b97a8", text3="#aab6c6", past="#5b6675",
            accent="#2bb3ad", accent_soft="#123536", page="#0a0d11", cap="#8b97a8")

# День К74/1. Время в минутах от полуночи.
PAIRS = [
    dict(n=1, t="09:00", s=540, e=575, subj="Основы алгоритмизации", k="лек",
         w="Иванов И.И.", r="3-301"),
    dict(n=2, t="10:45", s=645, e=740, subj="Базы данных", k="пр",
         w="Петрова А.С.", r="2-215"),
    dict(n=3, t="13:00", s=780, e=875, subj="Веб-разработка", k="лаб",
         w="Сидоров К.М.", r="1-104"),
    dict(n=4, t="14:45", s=885, e=980, subj="Иностр. язык в проф. коммуникации",
         k="пр", w="Прудова Л.Ю.", r="4-402"),
    dict(n=5, t="16:30", s=990, e=1085, subj="Физическая культура", k="пр",
         w="Титов А.В.", r="спортзал"),
]


def rounded(d, box, r, fill, outline=None, w=1):
    d.rounded_rectangle(box, radius=dp(r), fill=fill, outline=outline, width=w)


def tw(d, s, f):
    return d.textbbox((0, 0), s, font=f)[2]


def ellipsize(d, s, f, maxw):
    if tw(d, s, f) <= maxw:
        return s
    while s and tw(d, s + "…", f) > maxw:
        s = s[:-1]
    return s + "…"


def minute_word(n):
    n100, n10 = n % 100, n % 10
    if 11 <= n100 <= 14:
        return "минут"
    if n10 == 1:
        return "минуту"
    if 2 <= n10 <= 4:
        return "минуты"
    return "минут"


def draw_small(C, now_min, w_dp=140, h_dp=130):
    W, H = dp(w_dp), dp(h_dp)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rounded(d, (0, 0, W - 1, H - 1), 20, C["bg"], C["border"], 1)
    pad = dp(12)
    x0, x1 = pad, W - pad

    d.text((x0, pad), "К74/1", font=font(sp(12), True), fill=C["text2"])
    bw = tw(d, "I", font(sp(11), True)) + dp(12)
    rounded(d, (x1 - bw, pad - dp(1), x1, pad + dp(15)), 8, C["accent_soft"])
    d.text((x1 - bw + dp(6), pad + dp(1)), "I", font=font(sp(11), True), fill=C["accent"])

    cur = next((p for p in PAIRS if p["s"] <= now_min < p["e"]), None)
    nxt = next((p for p in PAIRS if p["s"] > now_min), None)
    y = pad + dp(24)

    if cur:
        state, chosen = "СЕЙЧАС", cur
    elif nxt:
        wait = nxt["s"] - now_min
        state = f"ЧЕРЕЗ {wait} {minute_word(wait).upper()}" if wait <= 90 else "ДАЛЬШЕ"
        chosen = nxt
    else:
        d.text((x0, y), "НА СЕГОДНЯ ВСЁ", font=font(sp(11), True), fill=C["text2"])
        d.text((x0, y + dp(18)), "Пар больше нет", font=font(sp(17), True), fill=C["text"])
        return img

    d.text((x0, y), state, font=font(sp(11), True), fill=C["accent"])
    d.text((x0, y + dp(15)), chosen["t"], font=font(sp(24), True), fill=C["text"])
    d.text((x0, y + dp(46)), ellipsize(d, chosen["subj"], font(sp(13)), x1 - x0),
           font=font(sp(13)), fill=C["text"])
    left = sum(1 for p in PAIRS if p["e"] > now_min) - (1 if cur else 0)
    foot = f"ауд. {chosen['r']}" + (f" · ещё {left}" if left > 0 else "")
    d.text((x0, H - pad - dp(11)), ellipsize(d, foot, font(sp(11)), x1 - x0),
           font=font(sp(11)), fill=C["text2"])
    return img


def draw_list(C, now_min, w_dp, h_dp, tall):
    W, H = dp(w_dp), dp(h_dp)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rounded(d, (0, 0, W - 1, H - 1), 20, C["bg"], C["border"], 1)
    pad = dp(12)
    x0, x1 = pad, W - pad

    bw = tw(d, "I неделя", font(sp(12), True)) + dp(18)
    rounded(d, (x1 - bw, pad, x1, pad + dp(20)), 8, C["accent_soft"])
    d.text((x1 - bw + dp(9), pad + dp(3)), "I неделя", font=font(sp(12), True),
           fill=C["accent"])
    d.text((x0, pad - dp(1)), "Сегодня, пятница", font=font(sp(17), True), fill=C["text"])
    # На низком виджете подпись под днём и подвал скрыты — иначе не остаётся места ни
    # одной строке пары (см. buildList: тот же флаг, та же причина).
    if tall:
        d.text((x0, pad + dp(20)), "К74/1 · 7 августа", font=font(sp(12)), fill=C["text2"])

    top = pad + dp((38 if tall else 22) + 8)
    bottom = H - pad - (dp(17) if tall else 0)
    rows = [p for p in PAIRS if tall or p["e"] > now_min]
    cur_i = next((i for i, p in enumerate(rows) if p["s"] <= now_min < p["e"]), -1)

    ROW_H, GAP = dp(52), dp(6)
    # Прокрутка: держим текущую пару в поле зрения (в живом виджете это делает ListView).
    visible = max(1, (bottom - top + GAP) // (ROW_H + GAP))
    start = 0
    if cur_i >= 0 and cur_i >= visible:
        start = min(cur_i - visible + 1, max(0, len(rows) - visible))

    y = top
    shown = 0
    for i in range(start, len(rows)):
        if y + ROW_H > bottom:
            break
        p = rows[i]
        is_now, is_past = (i == cur_i), (p["e"] <= now_min)
        rounded(d, (x0, y, x1, y + ROW_H), 12, C["row_now"] if is_now else C["row"])
        if is_now:
            d.rounded_rectangle((x0, y, x0 + dp(3), y + ROW_H), radius=dp(2),
                                fill=C["accent"])
        cm = C["past"] if (is_past and not is_now) else C["text"]

        ax = x0 + dp(6)
        if is_now:                                    # стрелка «идёт сейчас»
            cy = y + ROW_H // 2
            d.polygon([(ax + dp(3), cy - dp(6)), (ax + dp(13), cy),
                       (ax + dp(3), cy + dp(6))], fill=C["accent"])
        tx = ax + dp(20)
        d.text((tx, y + dp(8)), p["t"], font=font(sp(16), True), fill=cm)
        d.text((tx, y + dp(30)), "идёт" if is_now else f"{p['n']} пара",
               font=font(sp(11)), fill=C["accent"] if is_now else C["text2"])

        rw = tw(d, p["r"], font(sp(14), True))
        sx = tx + dp(60)
        sw = x1 - dp(10) - rw - dp(8) - sx
        d.text((sx, y + dp(7)), ellipsize(d, p["subj"], font(sp(16)), sw),
               font=font(sp(16)), fill=cm)
        d.text((sx, y + dp(30)), ellipsize(d, f"{p['k']} · {p['w']}", font(sp(12)), sw),
               font=font(sp(12)), fill=C["text2"])
        d.text((x1 - dp(10) - rw, y + dp(18)), p["r"], font=font(sp(14), True),
               fill=C["past"] if (is_past and not is_now) else C["text3"])
        y += ROW_H + GAP
        shown += 1

    if shown == 0:
        d.text((x0, top), "Пар нет", font=font(sp(14)), fill=C["text2"])
    if tall:
        d.text((x0, H - pad - dp(12)), "обновлено 18:40", font=font(sp(11)),
               fill=C["text2"])
    return img


def frame(C, now_min, title):
    small = draw_small(C, now_min)
    med = draw_list(C, now_min, 288, 130, tall=False)
    large = draw_list(C, now_min, 288, 280, tall=True)
    gap, top = dp(22), dp(56)
    W = gap * 4 + small.width + med.width + large.width
    H = top + max(small.height, med.height, large.height) + dp(46)
    img = Image.new("RGB", (W, H), C["page"])
    d = ImageDraw.Draw(img)
    d.text((dp(18), dp(14)), title, font=font(sp(17), True), fill=C["text"])
    d.text((dp(18), dp(34)), "GradeBookAI · виджет расписания · предпросмотр разметки",
           font=font(sp(11)), fill=C["cap"])
    x = gap
    for im, cap in ((small, "2×2 — что сейчас"), (med, "4×2 — ближайшие"),
                    (large, "4×4 — весь день")):
        img.paste(im, (x, top), im)
        d.text((x, top + max(small.height, med.height, large.height) + dp(12)), cap,
               font=font(sp(12)), fill=C["cap"])
        x += im.width + gap
    return img


def main(out):
    out = pathlib.Path(out)
    # Ключевые моменты дня: идёт пара -> перерыв с отсчётом -> следующая -> вечер.
    steps = [(560, "09:20 — идёт первая пара"),
             (630, "10:30 — до пары 15 минут"),
             (700, "11:40 — идёт вторая"),
             (800, "13:20 — идёт третья"),
             (900, "15:00 — идёт четвёртая"),
             (1000, "16:40 — идёт пятая"),
             (1100, "18:20 — на сегодня всё")]
    for name, C in (("light", LIGHT), ("dark", DARK)):
        tema = "Светлая" if name == "light" else "Тёмная"
        frames = [frame(C, m, f"{tema} тема · {t}") for m, t in steps]
        p = out / f"widget-anim-{name}.gif"
        frames[0].save(p, save_all=True, append_images=frames[1:],
                       duration=1600, loop=0, optimize=True)
        frames[1].save(out / f"widget-still-{name}.png")
        print("сохранено:", p, frames[0].size)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
