# -*- coding: utf-8 -*-
"""
build_widget_previews.py — картинки-превью виджетов для списка добавления.

🔥 ЗАЧЕМ (найдено 01.09.2026 по жалобе «друг вообще не видел виджетов»).
В `schedule_widget_*.xml` был только `android:previewLayout` — атрибут **API 31+**
(Android 12). На Android 7–11, а у нас `minSdkVersion = 24`, лаунчер его не понимает и
берёт `android:previewImage`; когда и его нет, в списке виджетов показывается либо иконка
приложения, либо пустое место — а часть оболочек (MIUI, EMUI, ColorOS) такой виджет в
списке просто не рисует. Со стороны это выглядит ровно как «виджетов нет».

Оба атрибута нужны ОДНОВРЕМЕННО: `previewLayout` даёт на новых версиях живой предпросмотр
с реальными данными, `previewImage` — статическую картинку на всех остальных.

⚠️ Картинки рисуются КОДОМ, а не берутся у дизайнера, и это осознанно: превью обязано
совпадать с тем, что человек получит, а раскладка виджета меняется вместе с продуктом.
Скриншот, снятый один раз руками, устареет молча — и в списке будет обещание, которое
виджет не выполняет.

Запуск:  python -X utf8 tools/build_widget_previews.py
"""
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                                     # pragma: no cover
    sys.exit("нужен Pillow:  pip install Pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "web", "android", "app", "src", "main", "res", "drawable-nodpi")

#Цвета — те же, что в values/widget_colors.xml (светлая тема): превью показывается на
#светлом фоне списка виджетов независимо от темы устройства.
BG = (255, 255, 255, 255)
ROW = (244, 246, 248, 255)
TEXT = (15, 27, 34, 255)
TEXT2 = (90, 105, 115, 255)
ACCENT = (232, 122, 26, 255)

#Размеры превью в пикселях. Лаунчеры масштабируют картинку под свою ячейку, поэтому важны
#ПРОПОРЦИИ, а не абсолют; берём с запасом, чтобы на плотных экранах не мылилось.
SIZES = {
    "widget_preview_2x2": (320, 320),
    "widget_preview_4x2": (640, 320),
    "widget_preview_4x4": (640, 640),
}

DEMO = [
    ("09:00", "Базы данных", "пр · Петрова А.С.", "2-215"),
    ("10:45", "Математика", "лек · Иванов П.П.", "1-104"),
    ("12:40", "Физика", "лаб · Сидорова М.И.", "3-301"),
    ("14:25", "Информатика", "пр · Дугаров Б.Ц.", "2-118"),
]


def _font(size):
    """Системный шрифт с кириллицей. Без него Pillow рисует квадраты вместо букв."""
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _w(d, text, font):
    """Ширина строки в пикселях. Нужна, чтобы колонки не наезжали друг на друга."""
    box = d.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def build(name, size):
    w, h = size
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = max(10, w // 24)
    _rounded(d, (0, 0, w - 1, h - 1), radius=w // 12, fill=BG)

    small = name.endswith("2x2")
    rows = 1 if small else (2 if name.endswith("4x2") else 4)

    #🔥 КЕГЛИ СЧИТАЮТСЯ ОТ ВЫСОТЫ СТРОКИ, А НЕ ОТ ВЫСОТЫ КАРТИНКИ (01.09.2026).
    #Раньше они брались долей от `h`, и это ломалось дважды: на 4×2 текст выходил
    #ужасно мелким (две строки в 320 px — доля та же, что и в 640), а на 4×4 наоборот
    #не влезал в строку. Строка — вот настоящая единица измерения этой раскладки.
    head_h = int(h * 0.085)
    y = pad + head_h
    gap = max(4, h // 90)
    row_h = int((h - y - pad) / rows) - gap

    #⚠️ Кегль шапки считается и от ШИРИНЫ тоже. Доля от высоты давала на квадратном
    #2×2 шестнадцать пикселей при картинке в 320 — подпись сливалась в серую полоску.
    head = _font(max(int(w * 0.075 if small else w * 0.045), int(head_h * 0.62)))
    if small:
        #⚠️ У 2×2 «строка» занимает всю высоту, и доли от неё дают обманчиво мелкий
        #кегль: 17 % от 250 px это 42 px на картинке, которую лаунчер ужмёт в ячейку
        #под 150 dp. Меряем от ШИРИНЫ — она у квадрата и есть ограничение, по которому
        #текст переносится и обрезается.
        title = _font(int(w * 0.13))
        body = _font(int(w * 0.105))
        meta = _font(int(w * 0.075))
    else:
        title = _font(int(row_h * 0.34))
        body = _font(int(row_h * 0.30))
        meta = _font(int(row_h * 0.22))

    #Шапка: день и неделя — то же, что показывает живой виджет.
    #⚠️ Цвет TEXT2, а не TEXT3: на превью в списке виджетов подпись читается на светлом
    #фоне лаунчера, и самый тусклый оттенок там просто сливается.
    #День — основным цветом: это заголовок карточки, а не служебная подпись. Тусклым
    #он сливался с фоном списка виджетов, где превью и рассматривают.
    d.text((pad, pad), "Пнд, 1 сентября", font=head, fill=TEXT)
    d.text((w - pad, pad), "неделя I", font=head, fill=TEXT2, anchor="ra")

    for i in range(rows):
        top = y + i * (row_h + gap)
        #⚠️ У 2×2 подложки строки НЕТ: сам виджет и есть одна карточка, и вторая рамка
        #внутри неё выглядела бы вложенным окном.
        if not small:
            _rounded(d, (pad, top, w - pad, top + row_h), radius=max(8, row_h // 4),
                     fill=ROW if i else (255, 240, 224, 255))
        time, subject, who, room = DEMO[i]
        tx = pad + max(8, w // 40)
        if small:
            #У 2×2 своя иерархия, и превью обязано её повторять: ЧТО за пара и КУДА идти
            #— крупно, время третьим. Обещание превью и вид виджета обязаны совпадать.
            d.text((tx, top + row_h * 0.06), "СЕЙЧАС", font=meta, fill=ACCENT)
            d.text((tx, top + row_h * 0.26), subject, font=title, fill=TEXT)
            d.text((tx, top + row_h * 0.56), f"ауд. {room}", font=body, fill=ACCENT)
            d.text((tx, top + row_h * 0.78), time, font=meta, fill=TEXT2)
        else:
            #🔥 Колонка времени шириной ПО ФАКТУ, а не долей ширины картинки: доля 14 %
            #давала 89 px при «09:00» шириной 95 — и время налезало на название предмета.
            #Измеряем и добавляем зазор.
            d.text((tx, top + row_h * 0.30), time, font=body,
                   fill=ACCENT if i == 0 else TEXT)
            sx = tx + _w(d, "00:00", body) + max(10, w // 40)
            #Аудиторию рисуем ПЕРВОЙ, чтобы знать её ширину: название предмета не должно
            #заезжать под неё на длинных строках.
            room_w = _w(d, room, meta)
            d.text((w - pad - max(8, w // 40), top + row_h * 0.34), room,
                   font=meta, fill=TEXT2, anchor="ra")
            limit = w - pad - max(8, w // 40) - room_w - max(12, w // 30)
            subj = subject
            while subj and sx + _w(d, subj, body) > limit:
                subj = subj[:-1]
            d.text((sx, top + row_h * 0.18), subj or subject, font=body, fill=TEXT)
            d.text((sx, top + row_h * 0.56), who, font=meta, fill=TEXT2)

    path = os.path.join(OUT, f"{name}.png")
    #⚠️ Пишем во временный файл и подменяем: на Windows запись поверх файла, который
    #кто-то держит открытым (просмотрщик, индексатор, gradle), падает с Errno 22 — и
    #сборка превью обрывается на середине, оставляя часть картинок старыми. Подмена
    #атомарна и такой гонки не знает.
    tmp = path + ".tmp"
    im.save(tmp, "PNG", optimize=True)
    os.replace(tmp, path)
    return path, os.path.getsize(path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, size in SIZES.items():
        path, sz = build(name, size)
        print(f"  {name:22s} {sz / 1024:6.1f} КБ")
