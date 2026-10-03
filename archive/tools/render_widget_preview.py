"""
Предпросмотр Android-виджета расписания.

Рисует РОВНО ТЕ ЖЕ размеры, отступы, кегли и цвета, что заданы в XML-разметке
(widget_schedule_small.xml / widget_schedule_list.xml / widget_schedule_row.xml)
и в widget_colors.xml. Это не «примерно похоже», а перенос чисел один в один —
иначе предпросмотр показывал бы не то, что человек увидит на телефоне.

⚠️ Это ИНСТРУМЕНТ СОГЛАСОВАНИЯ, а не тест: XML и этот файл могут разъехаться, если
править только один из них. Реальную сборку он не заменяет.
"""
import sys
from PIL import Image, ImageDraw, ImageFont

DENSITY = 3          # xxhdpi: 1dp = 3px
SCALE = DENSITY

REG = "C:/Windows/Fonts/segoeui.ttf"
BOLD = "C:/Windows/Fonts/segoeuib.ttf"
SEMI = "C:/Windows/Fonts/seguisb.ttf"

LIGHT = dict(
    bg="#FFFFFF", row="#F4F6F8", border="#E4E9ED",
    text="#0F1B22", text3="#46555F", text2="#7A8893",
    accent="#147C8B", accent_soft="#E3EFF1",
    wall=("#DCE3E8", "#C6D2DA"),
)
DARK = dict(
    bg="#171B1E", row="#1E2327", border="#272D32",
    text="#ECEEF0", text3="#AEB8BF", text2="#7E8A92",
    accent="#2BA6B8", accent_soft="#20343A",
    wall=("#0B0E10", "#161B1F"),
)

PAIRS = [
    dict(n=1, t="09:00-10:35", s="Основы алгоритмизации", k="лек", r="3-301", w="Иванов И.И."),
    dict(n=2, t="10:45-12:20", s="Базы данных", k="пр", r="2-215", w="Петрова А.С."),
    dict(n=3, t="13:00-14:35", s="Веб-разработка", k="лаб", r="1-104", w="Сидоров К.М."),
    dict(n=4, t="14:45-16:20", s="Иностр. язык в проф. коммуникации", k="пр", r="4-402",
         w="Прудова Л.Ю."),
]
NOW_INDEX = 1        # «идёт сейчас» — вторая пара


def dp(v):
    return int(round(v * SCALE))


def font(path, sp):
    return ImageFont.truetype(path, dp(sp))


def text_w(d, s, f):
    return d.textbbox((0, 0), s, font=f)[2]


def ellipsize(d, s, f, max_px):
    if text_w(d, s, f) <= max_px:
        return s
    while s and text_w(d, s + "…", f) > max_px:
        s = s[:-1]
    return s + "…"


def wrap(d, s, f, max_px, max_lines):
    """Перенос по словам с многоточием на последней строке — как ellipsize=end."""
    words, lines, cur = s.split(), [], ""
    for w in words:
        probe = (cur + " " + w).strip()
        if text_w(d, probe, f) <= max_px or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines:
        rest = " ".join(words[sum(len(x.split()) for x in lines):])
        if rest:
            lines[-1] = ellipsize(d, lines[-1] + " " + rest, f, max_px)
    return lines[:max_lines]


def rounded(d, box, radius, fill, outline=None, width=1):
    d.rounded_rectangle(box, radius=dp(radius), fill=fill, outline=outline,
                        width=dp(width) if outline else 0)


# ── МАЛЫЙ (2×2) ──────────────────────────────────────────────────────────────────
def draw_small(C, w_dp=140, h_dp=140):
    W, H = dp(w_dp), dp(h_dp)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rounded(d, (0, 0, W - 1, H - 1), 20, C["bg"], C["border"], 1)

    pad = dp(12)
    x0, x1 = pad, W - pad
    y = pad

    f_title = font(BOLD, 11)
    f_week = font(BOLD, 10)
    f_state = font(BOLD, 10)
    f_time = font(BOLD, 17)
    f_subj = font(REG, 12)
    f_foot = font(REG, 10)

    # шапка
    badge_txt = "I"
    bw = text_w(d, badge_txt, f_week) + dp(12)
    bh = dp(14)
    rounded(d, (x1 - bw, y, x1, y + bh), 8, C["accent_soft"])
    d.text((x1 - bw + (bw - text_w(d, badge_txt, f_week)) / 2, y + dp(1)),
           badge_txt, font=f_week, fill=C["accent"])
    d.text((x0, y + dp(1)), ellipsize(d, "К74/1", f_title, x1 - bw - x0 - dp(6)),
           font=f_title, fill=C["text2"])

    y += bh + dp(8)
    d.text((x0, y), "СЕЙЧАС", font=f_state, fill=C["accent"])
    y += dp(13)
    d.text((x0, y), "10:45–12:20", font=f_time, fill=C["text"])
    y += dp(23)
    for line in wrap(d, PAIRS[NOW_INDEX]["s"], f_subj, x1 - x0, 3):
        d.text((x0, y), line, font=f_subj, fill=C["text3"])
        y += dp(15)

    foot = f"ауд. {PAIRS[NOW_INDEX]['r']} · ещё 2"
    d.text((x0, H - pad - dp(12)), ellipsize(d, foot, f_foot, x1 - x0),
           font=f_foot, fill=C["text2"])
    return img


# ── СРЕДНИЙ / БОЛЬШОЙ ────────────────────────────────────────────────────────────
def rows_that_fit(h_dp, detailed):
    """Порт ScheduleWidgetProvider.rowsThatFit — те же числа, что в Java."""
    header = 34 if detailed else 18
    footer = 17 if detailed else 0
    avail = h_dp - 24 - header - 8 - footer
    row_h = (38 if detailed else 26) + 5
    return max(1, min(8, avail // row_h))


def draw_list(C, w_dp, h_dp, detailed):
    max_rows = rows_that_fit(h_dp, detailed)
    W, H = dp(w_dp), dp(h_dp)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rounded(d, (0, 0, W - 1, H - 1), 20, C["bg"], C["border"], 1)

    pad = dp(12)
    x0, x1 = pad, W - pad
    y = pad

    f_day = font(BOLD, 14)
    f_sub = font(REG, 11)
    f_week = font(BOLD, 10)
    f_pair = font(BOLD, 9)
    f_time = font(BOLD, 11)
    f_subj = font(REG, 12)
    f_meta = font(REG, 10)
    f_room = font(SEMI, 11)
    f_foot = font(REG, 9)

    # ── шапка. На низком виджете подпись под днём и подвал скрыты (см. buildList).
    badge_txt = "I неделя"
    bw = text_w(d, badge_txt, f_week) + dp(14)
    bh = dp(16)
    rounded(d, (x1 - bw, y + dp(1), x1, y + dp(1) + bh), 8, C["accent_soft"])
    d.text((x1 - bw + dp(7), y + dp(3)), badge_txt, font=f_week, fill=C["accent"])

    head_w = x1 - bw - x0 - dp(8)
    d.text((x0, y), ellipsize(d, "Сегодня, пятница", f_day, head_w), font=f_day, fill=C["text"])
    if detailed:
        d.text((x0, y + dp(18)), ellipsize(d, "К74/1 · 7 августа", f_sub, head_w),
               font=f_sub, fill=C["text2"])

    y += dp((34 if detailed else 18) + 8)

    # ── строки пар. Низкий виджет — только предстоящие; большой — весь день, где
    # прошедшие приглушены (см. buildList: разные размеры отвечают на разные вопросы).
    start_idx = 0 if detailed else NOW_INDEX
    rows = PAIRS[start_idx:][:max_rows]
    for i, p in enumerate(rows):
        idx = start_idx + i
        is_now = (idx == NOW_INDEX)
        is_past = (idx < NOW_INDEX)
        rh = dp(38 if detailed else 26)
        top = y
        rounded(d, (x0, top, x1, top + rh), 12,
                C["accent_soft"] if is_now else C["row"])
        if is_now:                                   # левая полоса 3dp — как в layer-list
            d.rounded_rectangle((x0, top, x0 + dp(3), top + rh), radius=dp(2), fill=C["accent"])

        cx = x0 + dp(8)
        room_w = text_w(d, p["r"], f_room)
        start = p["t"].split("-")[0]
        c_main = C["text2"] if is_past else C["text"]
        c_room = C["text2"] if is_past else C["text3"]

        if detailed:
            d.text((cx, top + dp(5)), "идёт" if is_now else f"{p['n']} пара",
                   font=f_pair, fill=C["accent"] if is_now else C["text2"])
            d.text((cx, top + dp(16)), start, font=f_time, fill=c_main)
            sx = cx + dp(52 + 8)
            sw = x1 - dp(8) - room_w - dp(6) - sx
            d.text((sx, top + dp(5)), ellipsize(d, p["s"], f_subj, sw), font=f_subj, fill=c_main)
            d.text((sx, top + dp(21)), ellipsize(d, f"{p['k']} · {p['w']}", f_meta, sw),
                   font=f_meta, fill=C["text2"])
            d.text((x1 - dp(8) - room_w, top + dp(13)), p["r"], font=f_room, fill=c_room)
        else:
            # компактная строка: время — предмет — аудитория в одну линию
            d.text((cx, top + dp(5)), start, font=f_time,
                   fill=C["accent"] if is_now else C["text"])
            sx = cx + dp(38 + 8)
            sw = x1 - dp(8) - room_w - dp(6) - sx
            d.text((sx, top + dp(4)), ellipsize(d, p["s"], f_subj, sw), font=f_subj, fill=C["text"])
            d.text((x1 - dp(8) - room_w, top + dp(5)), p["r"], font=f_room, fill=C["text3"])

        y = top + rh + dp(5)

    if detailed:
        rest = len(PAIRS) - start_idx - len(rows)
        foot = (f"ещё {rest} пары · " if rest > 0 else "") + "обновлено 18:40"
        d.text((x0, H - pad - dp(11)), ellipsize(d, foot, f_foot, x1 - x0),
               font=f_foot, fill=C["text2"])
    return img


# ── СБОРКА ЛИСТА ─────────────────────────────────────────────────────────────────
def sheet(C, name, title):
    # Габариты — реальные для сетки 5×4 на телефоне класса Pixel: именно их лаунчер
    # кладёт в OPTION_APPWIDGET_MIN_WIDTH/HEIGHT, по которым провайдер и выбирает
    # раскладку. Круглые «140×140» врали бы в пользу разметки.
    small = draw_small(C, 140, 130)
    medium = draw_list(C, 288, 130, detailed=False)
    large = draw_list(C, 288, 280, detailed=True)

    gap = dp(22)
    cap_h = dp(30)
    top = dp(58)
    W = gap * 4 + small.width + medium.width + large.width
    H = top + max(small.height, medium.height, large.height) + cap_h + gap

    img = Image.new("RGB", (W, H), C["wall"][0])
    d = ImageDraw.Draw(img)
    for i in range(H):                                # мягкий градиент «обоев»
        a = i / H
        c0 = tuple(int(C["wall"][0][j:j + 2], 16) for j in (1, 3, 5))
        c1 = tuple(int(C["wall"][1][j:j + 2], 16) for j in (1, 3, 5))
        d.line([(0, i), (W, i)], fill=tuple(int(c0[k] + (c1[k] - c0[k]) * a) for k in range(3)))

    f_h = font(BOLD, 15)
    f_c = font(REG, 11)
    head_col = LIGHT["text"] if C is LIGHT else DARK["text"]
    d.text((gap, dp(16)), title, font=f_h, fill=head_col)
    d.text((gap, dp(36)), "GradeBookAI · виджет расписания · предпросмотр разметки (xxhdpi)",
           font=f_c, fill=C["text2"])

    x = gap
    for im, cap in ((small, "2×2 — «что сейчас»"),
                    (medium, "4×2 — ближайшие пары"),
                    (large, "4×4 — весь день")):
        img.paste(im, (x, top), im)
        d.text((x, top + max(small.height, medium.height, large.height) + dp(8)),
               cap, font=f_c, fill=C["text2"])
        x += im.width + gap

    img.save(name)
    print("сохранено:", name, img.size)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    sheet(LIGHT, f"{out}/widget-preview-light.png", "Светлая тема")
    sheet(DARK, f"{out}/widget-preview-dark.png", "Тёмная тема")
