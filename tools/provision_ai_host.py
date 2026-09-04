#!/usr/bin/env python
"""
provision_ai_host.py — подготовить машину к тому, чтобы тяжёлые функции включились САМИ.

━━ ЗАЧЕМ ━━
Требование Ярослава (04.09.2026), дословно: «на проде наш сервак будет жить на пк ВСГУТУ
Ryzen 9 + 32 GB DDR5 + 16 гб видеопамяти. А значит нам нужно все то что мы отбросили или
в данный момент закомментили, остановили заготовить так чтобы мы просто перенесои сервак
и там само всё сразу включилось».

Продукт уже устроен правильно: он спрашивает «умеет ли ЭТА машина», а не читает тумблер.
Перевод, распознавание речи и озвучка включаются от НАЛИЧИЯ пакета и моделей. Значит
единственное, что нужно сделать при переезде, — поставить пакеты и модели. Этот скрипт
делает ровно это и НИЧЕГО больше: он не правит конфиги, не трогает базу и не включает
никаких флагов, потому что флагов и нет.

━━ КАК ПОЛЬЗОВАТЬСЯ ━━
    python tools/provision_ai_host.py            # холостой прогон: что есть, что встанет
    python tools/provision_ai_host.py --apply    # поставить пакеты и модели
    python tools/provision_ai_host.py --force    # ставить даже на слабой машине

⚠️ ХОЛОСТОЙ ПРОГОН — РЕЖИМ ПО УМОЛЧАНИЮ, и это не перестраховка. На уборке боевого диска
холостой прогон окупился целиком: он поймал `ssh` внутри `while read`, который съедал
stdin и молча обрабатывал одну строку из двадцати трёх. Здесь цена ошибки та же —
скачивание нескольких гигабайт не туда.

⚠️ ЧЕГО СКРИПТ НЕ ДЕЛАЕТ. Он не решает, работает ли функция: это решает сам продукт при
каждом запросе (`translate_service.status()`, `stt_service`, `tts_service`). Поэтому после
установки ничего перезапускать «чтобы применилось» не нужно — кроме самой службы, чтобы
новые пакеты попали в её процесс.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ_AI = os.path.join(ROOT, "server", "requirements-ai.txt")

#Что именно проверяем как «уже стоит». Пара (человеческое имя, импортируемый модуль).
#⚠️ Импортируемое имя НЕ совпадает с именем пакета (faster-whisper → faster_whisper), и
#это ровно то место, где список, написанный по памяти, врёт.
CHECKS = (
    ("распознавание речи (faster-whisper)", "faster_whisper"),
    ("перевод (argostranslate)", "argostranslate"),
    ("озвучка (torch)", "torch"),
    ("озвучка (numpy)", "numpy"),
)


def _installed(module: str) -> bool:
    """Стоит ли пакет — БЕЗ его импорта.

    ⚠️ Именно find_spec, а не `import`. Импорт `argostranslate` стоит четверть гигабайта
    и тянет за собой torch со stanza; платить это за ответ на вопрос «а он есть?» нельзя.
    Тот же довод, по которому `translate_service.status()` читает каталог моделей сам,
    вместо того чтобы спрашивать библиотеку.
    """
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _profile() -> dict:
    """Карточка машины из ЕДИНСТВЕННОГО места, которое на этот вопрос отвечает."""
    sys.path.insert(0, os.path.join(ROOT, "server"))
    from app import hostcaps
    return hostcaps.profile()


def _run(cmd: list, dry: bool) -> int:
    print("  $ " + " ".join(cmd))
    if dry:
        return 0
    return subprocess.call(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="выполнить установку (без него — только показать план)")
    ap.add_argument("--force", action="store_true",
                    help="ставить даже на машине ниже порога (см. hostcaps)")
    args = ap.parse_args()
    dry = not args.apply

    prof = _profile()
    gb = 1024 ** 3
    card = prof["gpu"]
    disk = prof.get("disk") or {}
    print("━━ ЖЕЛЕЗО ━━")
    print("  процессор:    %s" % (prof["cpu_model"] or "не определён"))
    print("  ядер:         %d" % prof["cpus"])
    print("  память:       %.1f ГБ всего, %.1f ГБ доступно%s"
          % (prof["ram_total"] / gb, prof["ram_available"] / gb,
             (", подкачка %.1f ГБ" % (prof["swap_total"] / gb))
             if prof.get("swap_total") else ""))
    print("  видеокарта:   %s" % (
        "%s, %d МБ" % (card["name"], card["vram_mb"]) if card["present"]
        else "не найдена (или нет драйверов — на работу продукта это не влияет)"))
    if disk.get("total"):
        print("  диск:         %.0f ГБ всего, %.0f ГБ свободно"
              % (disk["total"] / gb, disk["free"] / gb))
    print("  класс:        %s (%s)" % (prof["tier"], prof["why"]))

    print("\n━━ ЧТО УЖЕ СТОИТ ━━")
    missing = []
    for human, module in CHECKS:
        ok = _installed(module)
        print("  [%s] %s" % ("✓" if ok else " ", human))
        if not ok:
            missing.append(human)

    if prof["tier"] != "workstation" and not args.force:
        print("\n⛔ Машина НИЖЕ порога — ставить тяжёлый набор нельзя.")
        print("   Замер, а не прикидка: Argos требует +343 МБ сверх уже живого torch, и")
        print("   на арендованном VPS (960 МБ всего, 342 МБ свободных) он уходит в своп")
        print("   и утаскивает за собой журнал на единственном ядре.")
        print("   Если решение осознанное — повторите с --force.")
        return 2

    if not missing:
        print("\n✅ Все пакеты на месте. Осталось проверить модели — см. ниже.")

    print("\n━━ ПЛАН ━━" + ("  (ХОЛОСТОЙ ПРОГОН — ничего не делается)" if dry else ""))
    rc = 0

    if missing:
        print("\n1) Пакеты:")
        rc |= _run([sys.executable, "-m", "pip", "install", "-r", REQ_AI], dry)

    #Модели Whisper и Silero докачиваются САМИ при первом обращении — их здесь нет
    #намеренно: качать несколько гигабайт «на всякий случай» при подготовке машины
    #значит тратить время и диск на то, что продукт сделает сам и ровно тогда, когда
    #понадобится. Руками ставятся только модели Argos.
    print("\n2) Модели перевода (Argos; Whisper и Silero докачаются сами):")
    rc |= _run([sys.executable, os.path.join(ROOT, "tools", "install_argos_models.py")],
               dry)

    print("\n━━ ИТОГ ━━")
    if dry:
        print("  Холостой прогон. Чтобы выполнить: python tools/provision_ai_host.py --apply")
        print("  После установки перезапустите службу — новые пакеты попадут в её процесс:")
        print("     systemctl restart gradebook")
        return 0
    if rc != 0:
        print("  ⚠️ Один из шагов вернул ненулевой код. Ничего не считаем установленным —")
        print("     прочитайте вывод выше и повторите. Молчаливый частичный успех здесь")
        print("     хуже честной ошибки: половина функций работала бы, половина нет.")
        return 1
    print("  Готово. Проверить, что продукт это УВИДЕЛ (а не поверить на слово):")
    print("     curl -sS <адрес>/web/messenger/translate/status")
    print("     curl -sS <адрес>/web/vector/stt/status")
    print("  Ничего включать не нужно: обе ручки отвечают по факту наличия пакета.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
