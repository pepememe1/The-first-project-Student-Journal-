"""Замер настоящей цены Argos Translate в памяти — по паре языков, а не «в целом».

🔥 ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ. 29.08.2026 цену Argos оценили прикидкой («влезет, но
впритык») — и ошиблись на порядок важности: замер дал 863 МБ при 960 МБ на всей
боевой машине. Урок записан в CLAUDE.md дословно: «Замер, а не прикидка». Этот
скрипт существует, чтобы следующее решение о переводе на бою тоже опиралось на
цифру, а не на память о цифре.

Что меряем и почему именно это:
  • базовый расход процесса ДО импорта — чтобы вычесть сам Python;
  • цену ИМПОРТА пакета отдельно от цены МОДЕЛЕЙ (первое платится всегда, второе
    зависит от того, сколько пар мы держим);
  • прирост НА КАЖДУЮ пару по очереди — именно эта цифра решает, влезет ли
    «одна пара за раз»;
  • ВОЗВРАЩАЕТСЯ ли память после выгрузки модели. Это главный вопрос: если не
    возвращается, ограничение «держим одну пару» не даёт ничего, потому что за
    день сервер всё равно потрогает все четыре.

Запуск: python -X utf8 tools/measure_argos_memory.py
"""
import gc
import os
import sys


def rss_mb() -> float:
    """Сколько памяти реально занимает процесс, в мегабайтах.

    psutil есть не везде (на боевой машине его намеренно нет — §13, лишних пакетов
    не держим), поэтому на Linux читаем /proc сами, а на Windows спрашиваем ОС
    через ctypes. Замер, который не запускается на целевой машине, бесполезен.
    """
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1048576
    except Exception:
        pass
    if sys.platform.startswith("linux"):
        with open(f"/proc/{os.getpid()}/status", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        return 0.0
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    )
    return counters.WorkingSetSize / 1048576


PAIRS = [("ru", "en"), ("en", "ru"), ("en", "zh"), ("zh", "en")]
SAMPLES = {
    "ru": "Здравствуйте, у нас завтра две пары по математике в 314 аудитории.",
    "en": "Hello, we have two math classes tomorrow in room 314.",
    "zh": "你好，我们明天在314教室有两节数学课。",
}


def main() -> int:
    marks = []

    def mark(label: str) -> float:
        value = rss_mb()
        marks.append((label, value))
        print(f"{label:<46} {value:8.1f} МБ")
        return value

    print("=" * 66)
    print("ЗАМЕР ПАМЯТИ ARGOS TRANSLATE (RSS процесса)")
    print("=" * 66)
    base = mark("пустой процесс Python")

    try:
        import argostranslate.translate as at
    except Exception as exc:
        print(f"\nargostranslate не установлен: {exc}")
        return 2
    after_import = mark("после импорта argostranslate")
    print(f"{'  → цена самого пакета':<46} {after_import - base:8.1f} МБ")

    langs = {lang.code: lang for lang in at.get_installed_languages()}
    print(f"\nустановленные языки: {sorted(langs)}\n")

    engines = {}
    prev = after_import
    for src, dst in PAIRS:
        a, b = langs.get(src), langs.get(dst)
        if not a or not b:
            print(f"пара {src}->{dst}: модели нет, пропуск")
            continue
        engine = a.get_translation(b)
        if engine is None:
            print(f"пара {src}->{dst}: прямой модели нет, пропуск")
            continue
        #Модель CTranslate2 грузится ЛЕНИВО — до первого перевода она ещё не в памяти,
        #и замер сразу после get_translation() показал бы обнадёживающий ноль.
        out = engine.translate(SAMPLES[src])
        engines[(src, dst)] = engine
        now = mark(f"загружена и использована пара {src}->{dst}")
        print(f"{'  → прирост на эту пару':<46} {now - prev:8.1f} МБ")
        print(f"     проверка перевода: {out[:60]}")
        prev = now

    peak = prev
    print("\n" + "-" * 66)
    print("ВЫГРУЗКА: возвращается ли память, если модели отпустить")
    print("-" * 66)
    engines.clear()
    #У самой библиотеки свой кэш переводчиков — без его очистки наши ссылки ничего
    #не решают, и «выгрузка» была бы видимостью.
    for attr in ("_translation_cache", "translation_cache", "cached_translations"):
        if hasattr(at, attr):
            try:
                getattr(at, attr).clear()
                print(f"очищен кэш библиотеки: {attr}")
            except Exception:
                pass
    for lang in langs.values():
        for attr in ("translations_from", "translations_to"):
            box = getattr(lang, attr, None)
            if isinstance(box, list):
                box.clear()
    gc.collect()
    after_free = mark("после отпускания всех моделей")
    print(f"{'  → вернулось':<46} {peak - after_free:8.1f} МБ")

    print("\n" + "=" * 66)
    print("ИТОГ")
    print("=" * 66)
    print(f"пик со всеми парами:                {peak:8.1f} МБ")
    print(f"цена пакета без моделей:            {after_import - base:8.1f} МБ")
    if len(marks) > 3:
        one_pair = marks[2][1]
        print(f"пакет + ОДНА пара:                  {one_pair:8.1f} МБ "
              f"(это и есть нижняя граница «одна пара за раз»)")
    print(f"осталось занято после выгрузки:     {after_free:8.1f} МБ")
    print("\n⚠️ Сравнивать надо со СВОБОДНОЙ памятью боевой машины, а не с общей:")
    print("   там уже резидентен uvicorn с торчем ради Silero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
