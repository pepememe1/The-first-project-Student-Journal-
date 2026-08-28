# -*- coding: utf-8 -*-
"""
build_easter_audio.py — пережимает звук пасхалок в веб-формат.

Тот же приём, что у `build_activity_shots.py` и `build_mascot_anim.py`: исходник живёт в
репозитории, в поставку едет обработанный файл.

🔥 ЗАЧЕМ. Папка `web/public/easter/` весила 5.3 МБ, из них 4.2 МБ звук. Всё, что лежит
в `web/public/`, попадает не только на сайт:
    • в OTA-бандл Capgo, который КАЖДЫЙ телефон скачивает на каждое обновление;
    • в .exe (сборку ужимали со 135 МБ до 49 именно вычищением такого груза).
Пасхалка — приятная мелочь, которая срабатывает раз в сотню входов; платить за неё
мегабайтами трафика у всех пользователей несоразмерно.

🔥 ГЛАВНАЯ НАХОДКА: `office-amb-1.mp4` и `office-amb-2.mp4` — это ВИДЕОФАЙЛЫ (h264
640×360 внутри), а используются они как звук (`new Audio(src)` в `FnafOffice.vue`).
Видеодорожка качалась впустую и составляла заметную долю двух самых тяжёлых файлов.

⚠️ ФОРМАТ — AAC в контейнере `.m4a`, а не Opus. Opus меньше, но в Safari (iOS) он не
играет в `<audio>` без плясок, а сайт открывают и с айфонов. Экономия, которая у части
пользователей превращает пасхалку в тишину, — плохая экономия.

⚠️ МОНО для фонового шума и речи. Это не «сэкономили на качестве»: шум офиса и голос
рассказчика не имеют стереообраза, и вторая дорожка несёт ровно ту же информацию за
двойную цену. Музыке (`guitar`, `tree`) стерео оставлено.

Запуск:  python -X utf8 tools/build_easter_audio.py [--apply]
Без `--apply` только считает и показывает, что получится, — ничего не перезаписывая.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SND = os.path.join(ROOT, "web", "public", "easter", "snd")

#Битрейт и каналы по типу материала. Ключ — начало имени файла.
#⚠️ Речь и шум — моно; музыка — стерео. Разница слышна только на музыке.
PROFILES = [
    ("office-amb", 56, 1),      # фоновый шум офиса: ровный, стерео не несёт смысла
    ("narrator-", 64, 1),       # речь рассказчика
    ("vaas", 64, 1),            # речь
    ("johnny", 64, 1),          # речь
    ("guitar", 96, 2),          # музыка — стерео оставляем
    ("tree", 96, 2),            # музыка
    ("savepoint", 64, 1),       # короткий эффект
]
DEFAULT = (64, 1)


def ffmpeg_path() -> str:
    """Путь к ffmpeg: PATH, а если его там ещё нет — установленный winget'ом."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    guess = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages",
        "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
        "ffmpeg-9.0.1-full_build", "bin", "ffmpeg.exe")
    return guess if os.path.isfile(guess) else ""


def profile_for(name: str) -> tuple:
    for prefix, kbps, ch in PROFILES:
        if name.startswith(prefix):
            return (kbps, ch)
    return DEFAULT


def main() -> int:
    apply = "--apply" in sys.argv
    ff = ffmpeg_path()
    if not ff:
        print("ffmpeg не найден. Поставить:  winget install --id Gyan.FFmpeg -e")
        return 1
    if not os.path.isdir(SND):
        print(f"Нет папки со звуком: {SND}")
        return 1

    srcs = [f for f in sorted(os.listdir(SND))
            if os.path.splitext(f)[1].lower() in (".mp3", ".mp4", ".ogg", ".wav", ".m4a")]
    before = after = 0
    renames = []

    for fname in srcs:
        stem, ext = os.path.splitext(fname)
        src = os.path.join(SND, fname)
        kbps, ch = profile_for(stem)
        dst = os.path.join(SND, stem + ".m4a")
        tmp = dst + ".tmp.m4a"
        if os.path.abspath(dst) == os.path.abspath(src) and not apply:
            #Уже сжатый в нужный контейнер — всё равно прогоняем, битрейт мог быть выше.
            pass

        cmd = [ff, "-y", "-loglevel", "error", "-i", src,
               #-vn убирает видеодорожку: ради неё всё и затевалось у office-amb.
               "-vn", "-c:a", "aac", "-b:a", f"{kbps}k", "-ac", str(ch), tmp]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"  {fname}: ffmpeg не справился ({e.returncode})")
            if os.path.exists(tmp):
                os.remove(tmp)
            continue

        s_before = os.path.getsize(src)
        s_after = os.path.getsize(tmp)
        before += s_before
        after += s_after
        mark = ""
        #Не меняем файл, если он от этого ВЫРОС: перекодирование уже сжатого материала
        #иногда даёт больше исходного, и «оптимизация» стала бы ухудшением.
        if s_after >= s_before:
            mark = "  — больше исходного, пропускаем"
            after += s_before - s_after
            os.remove(tmp)
        elif apply:
            os.replace(tmp, dst)
            if ext.lower() != ".m4a":
                os.remove(src)
                renames.append((fname, stem + ".m4a"))
        else:
            os.remove(tmp)
        print(f"  {fname:26s} {s_before/1024:7.0f} КБ -> {s_after/1024:6.0f} КБ"
              f"  ({kbps}k, {'моно' if ch == 1 else 'стерео'}){mark}")

    print(f"\nИтого: {before/1024:.0f} КБ -> {after/1024:.0f} КБ")
    if renames:
        print("\n⚠️ ИМЕНА ИЗМЕНИЛИСЬ — поправь ссылки в web/src/components/easter/:")
        for a, b in renames:
            print(f"    {a}  ->  {b}")
    if not apply:
        print("\n(холостой прогон; чтобы записать — добавь --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
