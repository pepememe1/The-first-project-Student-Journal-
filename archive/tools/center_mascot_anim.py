"""
center_mascot_anim.py — центрирует маскота внутри кадра анимаций (WebP с альфой).

Проблема, которую чинит. Конвейер build_mascot_anim.py кропит все состояния по ОБЩЕМУ
bbox — это правильно (иначе маскот прыгал бы при смене состояния), но сам общий bbox
несимметричен: машущая рука в «приветствии» тянет его вправо, и в итоге персонаж стоит
левее центра кадра. На сайте и в мобильном приложении это видно сразу — Вектор прижат
к левому краю чата.

Почему правим ФАЙЛЫ, а не вёрстку. WebP один на все платформы: браузер (веб+мобилка) и
Qt на десктопе. Косметическая правка через CSS (object-position) чинила бы только веб,
а десктоп остался бы кривым — и следующая пересборка анимаций всё вернула бы.

Как считаем. НЕ по габаритам: в «приветствии» рука уходит в левый край кадра, в «покое»
хвост — в правый, и bbox даёт бессмысленный ответ. Считаем ЦЕНТР МАССЫ альфа-канала —
где на самом деле находится тело. По всем четырём состояниям он совпадает с точностью
до пары пикселей, поэтому поправка берётся одна на всех: разные поправки заставили бы
маскота дёргаться при переключении состояния.

Как правим. НЕ сдвигом внутри кадра — он срезал бы руку, которая уже касается края.
Дописываем ПРОЗРАЧНОЕ ПОЛЕ с нужной стороны: канва становится шире, арт не страдает,
object-contain в браузере и Qt на десктопе просто центрируют новый кадр.

    python tools/center_mascot_anim.py            # отчёт, файлы не трогаем
    python tools/center_mascot_anim.py --apply    # записать

Идемпотентен: если персонаж уже по центру (сдвиг меньше порога), файл не переписывается.
"""
import argparse
import os
import shutil
import sys

from PIL import Image, ImageSequence

#Параметры кодирования обязаны СОВПАДАТЬ с build_mascot_anim.py, иначе правка центровки
#заодно испортит анимацию. FPS=12 → 83 мс на кадр (пауза в покое сделана ДУБЛИРОВАНИЕМ
#кадров, а не длительностью — Qt плохо читает per-frame duration). disposal=2 очищает
#кадр перед отрисовкой следующего: без него полупрозрачные кадры наслаиваются и за
#маскотом тянется «призрак».
FPS = 12
FRAME_MS = int(1000 / FPS)
DISPOSAL = 2

#Куда смотреть. МЕСТО ОДНО — оттуда файлы едут и на сайт, и в мобильное приложение
#(OTA), и в .exe (там та же SPA в окне WebView2).
#⚠️ Второй целью здесь была копия `emotions/анимации` «для десктопа». Она пережила снос
#Qt на две недели и жила мёртвым побайтовым дублем (6 файлов, 2.3 МБ в git), при том что
#`build_mascot_anim.py` в своей же шапке писал: «копия больше никем не читается». Удалена
#31.08.2026 вместе с этой строкой — иначе следующий прогон центровки завёл бы её заново.
TARGETS = [
    os.path.join("web", "public", "mascot", "anim"),
]
STATES = ["idle", "greeting", "thinking", "speaking"]

#Меньше этого сдвига не трогаем: разница в пару пикселей незаметна, а лишняя
#перекодировка WebP — это потеря качества на ровном месте.
MIN_SHIFT_PX = 3


def _frames(path):
    """Кадры анимации + их длительности. Длительность обязана сохраниться: в idle в цикл
    вшита пауза ~2 c (иначе маскот «моргает»), и потеряй мы её — анимация поедет."""
    im = Image.open(path)
    out = []
    for fr in ImageSequence.Iterator(im):
        out.append((fr.convert("RGBA"), fr.info.get("duration", 80)))
    loop = im.info.get("loop", 0)
    return out, loop


def _mass_center_x(paths):
    """Средний по всем состояниям центр массы альфы (в пикселях) и размер кадра.

    Габариты (bbox) тут не годятся: жест рукой в «приветствии» дотягивается до края
    кадра и утаскивает измерение за собой. Центр массы отражает, где реально тело."""
    import numpy as np
    centers, size = [], None
    for p in paths:
        frames, _ = _frames(p)
        total = None
        for fr, _d in frames:
            size = fr.size
            col = np.array(fr)[:, :, 3].astype(np.float64).sum(axis=0)
            total = col if total is None else total + col
        if total is None or total.sum() == 0:
            continue
        x = np.arange(len(total))
        centers.append((total * x).sum() / total.sum())
    return (sum(centers) / len(centers) if centers else 0.0), size


def _pad_file(path, pad_left, apply: bool):
    """Дописывает прозрачное поле слева, сохраняя тайминги и зацикливание.

    Именно поле, а не сдвиг: у «приветствия» рука уже касается левого края, и сдвиг
    внутри прежней канвы отрезал бы её."""
    frames, loop = _frames(path)
    shifted = []
    for fr, _d in frames:
        w, h = fr.size
        canvas = Image.new("RGBA", (w + pad_left, h), (0, 0, 0, 0))
        canvas.paste(fr, (pad_left, 0))
        shifted.append(canvas)
    if not apply:
        return len(shifted)
    shutil.copy2(path, path + ".bak")     #откат под рукой, если результат не понравится
    shifted[0].save(
        path, format="WEBP", save_all=True, append_images=shifted[1:],
        duration=FRAME_MS, loop=loop, disposal=DISPOSAL,
        lossless=False, quality=80, method=4, exact=True,   #exact — не портить альфу
    )
    return len(shifted)


def main() -> int:
    ap = argparse.ArgumentParser(description="Центрирование маскота в кадре анимаций")
    ap.add_argument("--apply", action="store_true", help="записать (без флага — отчёт)")
    args = ap.parse_args()

    paths = []
    for d in TARGETS:
        for s in STATES:
            p = os.path.join(d, f"{s}.webp")
            if os.path.exists(p):
                paths.append(p)
    if not paths:
        print("Файлы анимаций не найдены — нечего центрировать.")
        return 1

    cx, size = _mass_center_x(paths)
    w = size[0]
    dx = (w / 2) - cx                      #на столько тело левее центра кадра
    #Чтобы центр массы оказался в середине НОВОЙ канвы, поля слева нужно ровно 2*dx.
    pad_left = int(round(2 * dx))

    print("=" * 68)
    print("ЦЕНТРИРОВАНИЕ МАСКОТА")
    print("=" * 68)
    print(f"  кадр                : {size[0]}x{size[1]}")
    print(f"  центр массы тела    : {cx:.0f} (центр кадра {w / 2:.0f})")
    print(f"  тело левее центра на: {dx:.0f} px")
    print(f"  поле слева          : {pad_left} px  → новая ширина {w + pad_left}")
    if pad_left <= 0:
        print("  Тело правее центра или уже по центру — поле не нужно, файлы не трогаем.")
        return 0
    if abs(dx) < MIN_SHIFT_PX:
        print(f"  Уже по центру (меньше {MIN_SHIFT_PX} px) — файлы не трогаем.")
        return 0

    for p in paths:
        n = _pad_file(p, pad_left, args.apply)
        print(f"  {'обработан' if args.apply else 'к правке'}: {p} ({n} кадров)")
    if args.apply:
        print("\nГОТОВО. Рядом с каждым файлом лежит .bak — если результат не понравится, "
              "верните его.")
        print("Не забудьте пересобрать веб (npm run build) и .exe — файлы бандлятся внутрь.")
    else:
        print("\nХОЛОСТОЙ ПРОГОН: файлы не изменены. Записать — с флагом --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
