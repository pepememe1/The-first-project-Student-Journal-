"""
build_android_icons.py — иконки Android-приложения из общего `icon.png`.

Запуск (из корня репозитория):
    python tools/build_android_icons.py

━━ ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ ━━
Значок в репозитории один — `icon.png` (гексагон GB, он же фавикон сайта и иконка
десктопа). Android же хочет его в СЕМИ размерах и в ДВУХ ролях сразу, и разложить это
руками — верный способ обновить половину файлов. Ровно так и вышло: на телефонах
осталась иконка, не похожая ни на сайт, ни на десктоп.

━━ ГЛАВНОЕ ПРО «АДАПТИВНУЮ» ИКОНКУ (Android 8+) ━━
Начиная с Android 8 лаунчер НЕ показывает `ic_launcher.png`. Он берёт два слоя из
`mipmap-anydpi-v26/ic_launcher.xml` — `ic_launcher_background` и `ic_launcher_foreground` —
и обрезает их по своей маске (круг, квадрат со скруглением, «капля» — у каждой прошивки
своя). Поэтому обновление одного `ic_launcher.png` НЕ меняет то, что человек видит на
экране: файл просто перестал использоваться.

Вторая ловушка — размер. Слои рисуются на холсте 108 dp, а видно из них только
центральные 72 dp (66,7 %) — остальное съедает маска и параллакс. В нашем XML к этому
добавлен `inset 16,7 %`, то есть картинка ещё раз ужимается до тех же 66,7 %. Прежний
`ic_launcher_foreground.png` уже содержал широкие поля, и после вставки гексагон занимал
меньше трети значка — со стороны это и читается как «старый логотип».

Поэтому здесь передний слой делается ПОД ОБРЕЗ: гексагон растягивается на весь холст,
а в безопасную зону его ставит уже `inset` из XML. Меняете XML — пересчитайте масштаб.
"""
import os
import sys

try:
    from PIL import Image
except ImportError:                                     # pragma: no cover
    sys.exit("Нужен Pillow: pip install Pillow")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "icon.png")
RES = os.path.join(ROOT, "web", "android", "app", "src", "main", "res")

#Холст слоя адаптивной иконки — 108 dp. Ниже размеры в пикселях по плотностям экрана.
LAYER_SIZES = {
    "mipmap-ldpi": 81,
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}
#Обычная («устаревшая») иконка — 48 dp. Её показывают Android 7 и ниже, а также часть
#лаунчеров в списке приложений. Здесь гексагон вписываем сами, `inset` к ней не
#применяется — отсюда поле в 4 %.
LEGACY_SIZES = {
    "mipmap-ldpi": 36,
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

#Фон адаптивной иконки. Белый — как у обычной иконки и у карточки в магазине: гексагон
#двухцветный и на цветной подложке теряет форму.
BACKGROUND = (255, 255, 255, 255)


def _logo() -> Image.Image:
    """Гексагон, обрезанный по непрозрачным пикселям (без полей исходника)."""
    im = Image.open(SRC).convert("RGBA")
    box = im.split()[3].getbbox()
    if box is None:
        sys.exit(f"{SRC}: изображение полностью прозрачное")
    return im.crop(box)


def _fit(logo: Image.Image, canvas: int, margin: float) -> Image.Image:
    """Вписать гексагон в квадратный холст, сохранив пропорции."""
    inner = max(1, int(round(canvas * (1.0 - 2 * margin))))
    w, h = logo.size
    scale = min(inner / w, inner / h)
    resized = logo.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                          Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(resized, ((canvas - resized.width) // 2, (canvas - resized.height) // 2),
              resized)
    return out


def _rebuild_splashes(logo: Image.Image) -> int:
    """Заставка запуска — тот же гексагон, все размеры и обе темы.

    Файлы уже разложены Capacitor'ом по `drawable-{port,land}[-night]-*`, поэтому
    размеры и цвет фона берём из СУЩЕСТВУЮЩИХ картинок, а не задаём списком: список
    из 27 записей пришлось бы править при каждой смене набора плотностей, и он
    молча разъехался бы с тем, что реально лежит в проекте.

    На заставке был старый одноцветный гексагон — тот самый «логотип не как в вебе»:
    иконку когда-то обновили, а заставку забыли, и первое, что человек видел при
    запуске, было прошлой версией знака."""
    import glob
    count = 0
    for path in glob.glob(os.path.join(RES, "drawable*", "splash.png")):
        old = Image.open(path).convert("RGBA")
        w, h = old.size
        background = old.getpixel((1, 1))          #белый или тёмный — по теме папки
        canvas = Image.new("RGBA", (w, h), background)
        #Знак занимает пятую часть узкой стороны: так он одинаково смотрится и на
        #узком телефоне, и в альбомной ориентации планшета.
        target = max(1, int(round(min(w, h) * 0.20)))
        scale = min(target / logo.width, target / logo.height)
        mark = logo.resize((max(1, round(logo.width * scale)),
                            max(1, round(logo.height * scale))), Image.LANCZOS)
        canvas.alpha_composite(mark, ((w - mark.width) // 2, (h - mark.height) // 2))
        canvas.save(path)
        count += 1
    return count


def main() -> int:
    if not os.path.isfile(SRC):
        sys.exit(f"не найден {SRC}")
    logo = _logo()
    written = 0

    for folder, size in LAYER_SIZES.items():
        out_dir = os.path.join(RES, folder)
        os.makedirs(out_dir, exist_ok=True)
        #Передний слой — почти под обрез: в безопасную зону его убирает `inset 16,7 %`
        #из mipmap-anydpi-v26/ic_launcher.xml (108 dp → 72 dp). Поле 5 % оставлено с
        #запасом: гарантированно видимый круг у адаптивной иконки — 66 dp, и без него
        #верхняя и нижняя вершины гексагона срезались бы круглой маской.
        _fit(logo, size, 0.05).save(os.path.join(out_dir, "ic_launcher_foreground.png"))
        Image.new("RGBA", (size, size), BACKGROUND).save(
            os.path.join(out_dir, "ic_launcher_background.png"))
        written += 2

    for folder, size in LEGACY_SIZES.items():
        out_dir = os.path.join(RES, folder)
        os.makedirs(out_dir, exist_ok=True)
        flat = Image.new("RGBA", (size, size), BACKGROUND)
        shaped = _fit(logo, size, 0.04)
        flat.alpha_composite(shaped)
        flat.save(os.path.join(out_dir, "ic_launcher.png"))
        #Круглая иконка — тот же рисунок: гексагон вписан с полем и в круг попадает
        #целиком. Отдельная отрисовка дала бы два слегка разных значка на одном телефоне.
        flat.save(os.path.join(out_dir, "ic_launcher_round.png"))
        written += 2

    written += _rebuild_splashes(logo)
    print(f"готово: {written} файлов в {RES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
