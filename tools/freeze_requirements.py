#!/usr/bin/env python
"""
freeze_requirements.py — зафиксировать ТОЧНЫЕ версии зависимостей для поставки.

━━ ЗАЧЕМ (п. 2.5 docs/PLAN-HARDENING.txt) ━━
В `requirements.txt` везде `>=`. Для разработки это правильно — иначе мы застрянем на
версиях позапрошлого года. Для ПОСТАВКИ это дыра: покупатель ставит по тому же файлу
через полгода и получает ДРУГУЮ комбинацию версий, которую никто никогда не проверял. А
на приёмке и при разборе инцидента спрашивают ровно одно: «какая именно сборка у вас
работает».

`uv.lock` у нас есть, но ни CI, ни боевая машина им не пользуются — они ставят по
`requirements.txt`. Замок, которым никто не пользуется, отличается от отсутствующего
только тем, что даёт ложное спокойствие (тот же класс, что красный CI, в который верили).

━━ ЧТО ДЕЛАЕТ ━━
Снимает СЛЕПОК ТЕКУЩЕГО ОКРУЖЕНИЯ (`pip freeze`) и пишет `server/requirements.lock.txt`.
Установщик (`deploy/install.sh`) берёт замок, ЕСЛИ ОН ЕСТЬ, и только иначе — обычный
`requirements.txt`.

    python tools/freeze_requirements.py            # показать, что попадёт в замок
    python tools/freeze_requirements.py --write    # записать файл

⚠️ **Снимать замок надо НА МАШИНЕ, ГДЕ ПРОГОН БЫЛ ЗЕЛЁНЫМ.** Смысл замка не в том, чтобы
где-то лежали числа, а в том, что зафиксирована ПРОВЕРЕННАЯ комбинация. Снимок с машины,
на которой тесты не гоняли, — это просто другой набор чисел.

⚠️ **Замок НЕ заменяет `requirements.txt` и не отменяет его.** Тот остаётся объявлением
намерения («нужен fastapi не ниже 0.110»), замок — фиксацией факта. Две роли, два файла;
слить их значило бы либо запретить обновления, либо потерять воспроизводимость.

⚠️ **Тяжёлый набор (`requirements-ai.txt`) в замок НЕ входит.** Он ставится не везде, и
приколотить torch к версии на машине сборки значило бы сломать установку там, где нужна
сборка под другую видеокарту.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(ROOT, "server", "requirements.txt")
LOCK = os.path.join(ROOT, "server", "requirements.lock.txt")

#Пакеты тяжёлого набора и инструменты разработки в замок поставки не идут.
SKIP = {"torch", "numpy", "faster-whisper", "argostranslate", "ctranslate2", "stanza",
        "nuitka", "pyinstaller", "ruff", "bandit", "mypy", "pip-audit", "playwright"}


def _declared() -> set:
    """Имена, объявленные в server/requirements.txt и ПРИМЕНИМЫЕ к этой платформе.

    ⚠️ Маркеры окружения (`; sys_platform == "linux"`) обязаны учитываться. Иначе на
    Windows скрипт объявляет `sqlcipher3-binary` пропавшим — а его там законно нет
    (готового wheel под Windows не существует), и отказ был бы ложной тревогой.
    Ложная тревога у проверки поставки опаснее, чем кажется: её быстро научаются
    обходить флагом, и вместе с ней перестают замечать настоящую.
    """
    out = set()
    with open(REQ, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            spec, _, marker = line.partition(";")
            if marker.strip():
                try:
                    #Разбираем маркер тем же способом, каким его понимает pip.
                    from packaging.markers import Marker
                    if not Marker(marker.strip()).evaluate():
                        continue
                except ImportError:
                    #Без packaging — грубо, но в нужную сторону: единственный маркер у
                    #нас про платформу, и ошибиться безопаснее в сторону пропуска.
                    if "sys_platform" in marker and sys.platform not in marker:
                        continue
                except Exception:
                    pass
            name = re.split(r"[><=!~;\[\s]", spec, 1)[0].strip().lower()
            if name:
                out.add(name)
    return out


def _frozen() -> dict:
    """{имя: версия} из текущего окружения."""
    out = {}
    res = subprocess.run([sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
                         capture_output=True, text=True)
    for line in (res.stdout or "").splitlines():
        if "==" not in line or line.startswith("#"):
            continue
        name, _, ver = line.partition("==")
        out[name.strip().lower()] = ver.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="записать server/requirements.lock.txt")
    ap.add_argument("--force", action="store_true",
                    help="снять замок не на Linux (для поставки не годится)")
    args = ap.parse_args()

    declared = _declared()
    frozen = _frozen()
    if not frozen:
        print("pip freeze ничего не вернул — окружение пустое?", file=sys.stderr)
        return 1

    missing = sorted(d for d in declared if d not in frozen and d not in SKIP)
    pins = {n: v for n, v in frozen.items() if n not in SKIP}

    print("Объявлено в requirements.txt: %d" % len(declared))
    print("Будет закреплено (с транзитивными): %d" % len(pins))
    if missing:
        print("\n⚠️ ОБЪЯВЛЕНО, НО НЕ УСТАНОВЛЕНО — замок вышел бы НЕПОЛНЫМ:")
        for name in missing:
            print("   " + name)
        print("Поставьте зависимости (pip install -r server/requirements.txt) и повторите.")
        print("Замок с дырой хуже отсутствующего: он выглядит как гарантия.")
        return 2

    body = ["# server/requirements.lock.txt — ТОЧНЫЕ версии проверенной комбинации.",
            "#",
            "# Сгенерирован tools/freeze_requirements.py. Руками не правят: правка здесь",
            "# означает комбинацию, которую никто не проверял, — то есть ровно то, от чего",
            "# замок и защищает.",
            "#",
            "# Ставится установщиком автоматически, если файл есть рядом с requirements.txt.",
            "# Обновлять — после зелёного полного прогона на той же машине.",
            ""]
    body += ["%s==%s" % (n, v) for n, v in sorted(pins.items())]
    text = "\n".join(body) + "\n"

    if args.write and sys.platform != "linux" and not args.force:
        # 🔥 ТИХАЯ ЛОВУШКА, ЕСЛИ ЭТОГО НЕ ЗАПРЕТИТЬ. Боевой сервер — Linux, и часть
        # пакетов объявлена только для него (`sqlcipher3-binary; sys_platform ==
        # "linux"` — шифрование файла базы). Снимок с Windows их не содержит по
        # построению: маркер честно исключил их выше. Такой замок ВЫГЛЯДИТ полным,
        # ставится без единой ошибки — и оставляет боевую машину без шифрования ПДн.
        # Отказ громкий, потому что заметить это иначе можно только на проверке.
        print("\n⛔ Замок снимается на LINUX — той системе, где сервер работает.")
        print("   Здесь %s: пакеты, объявленные только для Linux (шифрование базы"
              " SQLCipher)," % sys.platform)
        print("   в снимок не попадут, и замок будет выглядеть полным, не будучи им.")
        print("   Снимите его на боевой машине после зелёного прогона.")
        print("   Если это осознанно (например, замок только для разработки) — --force.")
        return 3

    if args.write:
        with open(LOCK, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("\nЗаписано: %s" % LOCK)
        if sys.platform != "linux":
            print("⚠️ Снят НЕ на Linux — для поставки этот замок не годится.")
    else:
        print("\n(холостой прогон; чтобы записать — повторите с --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
