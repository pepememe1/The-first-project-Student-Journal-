"""
Сторож заготовки под машину ВСГУТУ: тяжёлые функции обязаны включиться САМИ.

━━ ЧТО ЗДЕСЬ ЗАЩИЩАЕТСЯ ━━
Требование Ярослава (04.09.2026): «нам нужно все то что мы отбросили или в данный момент
закомментили, остановили заготовить так чтобы мы просто перенесои сервак и там само всё
сразу включилось».

Главный проверяемый инвариант — **зависимость не объявляют комментарием**.

🔥 Почему это не придирка к стилю. До 04.09.2026 `faster-whisper` и `argostranslate`
лежали в `server/requirements.txt` закомментированными, с припиской «раскомментировать
ТОЛЬКО на машине, где есть память». Закомментированную строку не поставит НИ ОДНА
команда и не увидит НИ ОДИН инструмент: это не объявление зависимости, а записка
человеку с просьбой вспомнить. А вспоминают такое ровно в день переезда, когда некогда.
Тот же класс, за который в проекте уже платили:
  • список модулей в `build_nuitka.sh` с припиской «проверено полным перебором» — был
    верен в день написания и молча устарел, собранный .exe перестал запускаться;
  • порог хранилища вложений, пока он был тумблером, а не проверкой свободного места.

Правильная форма — отдельный файл `server/requirements-ai.txt`, который СТАВИТСЯ одной
командой (`tools/provision_ai_host.py --apply`) и виден pip.

⚠️ Чего этот сторож НЕ проверяет: что пакеты реально установлены. На машине разработки и
в CI их нет и быть не должно — проверять надо ОБЪЯВЛЕНИЕ, а не окружение прогона. Тест,
зависящий от того, чья это машина, у нас уже был дважды (`config.IS_PROD` и фикстура
переводчика), и оба раза «зелено у одного, красно у другого» находилось не сразу.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQ_SERVER = os.path.join(ROOT, "server", "requirements.txt")
REQ_AI = os.path.join(ROOT, "server", "requirements-ai.txt")
REQ_ROOT = os.path.join(ROOT, "requirements.txt")
PROVISION = os.path.join(ROOT, "tools", "provision_ai_host.py")

#Тяжёлый набор: то, что живёт ТОЛЬКО на машине с памятью и ядрами.
HEAVY = ("faster-whisper", "argostranslate", "torch")

#Строка, которая ВЫГЛЯДИТ объявлением зависимости, но закомментирована.
#Ищем «# имя-пакета» со спецификатором версии или без, но не обычную прозу: у прозы
#после решётки идёт слово с пробелом и кириллицей, а не `pkg>=1.2`.
_COMMENTED_DEP = re.compile(r"^\s*#\s*([A-Za-z][A-Za-z0-9._-]{2,})\s*(?:\[[^\]]+\])?\s*"
                            r"(?:[><=!~]=?\s*[0-9][0-9A-Za-z.*+-]*)\s*(?:;.*)?$")


def _commented_dep(line: str) -> str:
    """Имя пакета, если строка — закомментированное объявление зависимости, иначе ''."""
    m = _COMMENTED_DEP.match(line)
    return m.group(1) if m else ""


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _declared(path: str) -> set:
    """Имена пакетов, объявленных ПО-НАСТОЯЩЕМУ (без комментариев)."""
    out = set()
    for line in _read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[><=!~;\[\s]", line, 1)[0].strip().lower()
        if name:
            out.add(name)
    return out


# ─────────────────────────────────────────────────────────────────────────────────
# ГЛАВНОЕ СВОЙСТВО: зависимость не объявляют комментарием
# ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [REQ_SERVER, REQ_ROOT, REQ_AI])
def test_no_dependency_is_declared_by_commenting_it_out(path):
    """Ни в одном requirements не должно быть закомментированного пакета.

    Такая строка — это не «выключенная зависимость», а забытая настройка: поставить её
    невозможно ничем, кроме как вспомнив и убрав решётку руками.
    """
    bad = []
    for i, line in enumerate(_read(path).splitlines(), 1):
        name = _commented_dep(line)
        if name:
            bad.append("%s:%d  %s" % (os.path.basename(path), i, line.strip()))
    assert not bad, (
        "зависимость объявлена комментарием — так она не поставится никогда:\n  "
        + "\n  ".join(bad)
        + "\nНужно либо объявить её по-настоящему (в requirements-ai.txt, если пакет "
          "тяжёлый), либо удалить строку вместе с иллюзией, что она что-то включает."
    )


def test_the_commented_dependency_detector_actually_works():
    """ОБРАТНЫЙ ХОД. Сторож, который не проверили откатом, скорее всего не работает.

    Берём ДОСЛОВНО те строки, из-за которых заведён этот файл, и требуем, чтобы проверка
    их поймала. Рядом — проза, которую она поймать НЕ должна: ложное срабатывание здесь
    вреднее пропуска, потому что оно заставит удалять объяснения из комментариев.
    """
    must_catch = (
        "# faster-whisper>=1.0",
        "# argostranslate>=1.9",
        "#psycopg2-binary>=2.9",
        "  # torch>=2.0",
        "# sqlcipher3-binary>=0.5; sys_platform == 'linux'",
    )
    for line in must_catch:
        assert _commented_dep(line), "проверка НЕ увидела закомментированный пакет: %r" % line

    must_ignore = (
        "# Перевод мессенджера — ЛОКАЛЬНЫЙ офлайновый переводчик (29.08.2026).",
        "# ⚠️ Пакет тянет ctranslate2 (~40 МБ) — тот же движок, что у faster-whisper.",
        "# ============================================================",
        "#     python tools/provision_ai_host.py --apply",
        "# Python 3.10+",
        "",
        "fastapi>=0.110          # веб-фреймворк API",
    )
    for line in must_ignore:
        assert not _commented_dep(line), "ложное срабатывание на прозе: %r" % line


# ─────────────────────────────────────────────────────────────────────────────────
# РАЗДЕЛЕНИЕ НАБОРОВ
# ─────────────────────────────────────────────────────────────────────────────────

def test_heavy_packages_are_declared_only_in_the_ai_file():
    """Тяжёлое не должно приехать на слабую машину обычной установкой.

    Это не вкусовщина: на нынешнем VPS 960 МБ, и Argos требует +343 МБ сверх уже живого
    torch при 342 МБ свободных (замер `tools/measure_argos_memory.py`). Попади он в
    основной requirements — первый же `pip install -r` на бою увёл бы журнал в своп.
    """
    base = _declared(REQ_SERVER) | _declared(REQ_ROOT)
    ai = _declared(REQ_AI)
    for pkg in HEAVY:
        assert pkg not in base, (
            "%s объявлен в ОСНОВНОМ requirements — он приедет на машину, где для него "
            "нет памяти" % pkg)
        assert pkg in ai, (
            "%s пропал из server/requirements-ai.txt: на машине ВСГУТУ он не поставится, "
            "и функция молча не включится" % pkg)


def test_every_heavy_module_the_server_lazily_imports_is_declared():
    """СВОЙСТВО, а не список: что код импортирует лениво — то и обязано быть объявлено.

    Ленивый импорт тяжёлого пакета — наш штатный приём («нет пакета → честный отказ»).
    Но если такой пакет не объявлен НИГДЕ, отказ станет вечным: поставить его будет
    неоткуда. Здесь ловится именно этот разрыв.
    """
    app_dir = os.path.join(ROOT, "server", "app")
    #Соответствие «имя при импорте → имя пакета». Разъезжается оно постоянно
    #(faster-whisper → faster_whisper), поэтому держим явно.
    module_to_package = {"faster_whisper": "faster-whisper",
                         "argostranslate": "argostranslate",
                         "torch": "torch",
                         "numpy": "numpy"}
    pattern = re.compile(r"^\s+import\s+(%s)\b" % "|".join(module_to_package))
    found = set()
    for name in os.listdir(app_dir):
        if not name.endswith(".py"):
            continue
        for line in _read(os.path.join(app_dir, name)).splitlines():
            m = pattern.match(line)
            if m:
                found.add(module_to_package[m.group(1)])
    assert found, "не найдено ни одного ленивого импорта — проверка перестала проверять"
    declared = _declared(REQ_AI)
    missing = sorted(p for p in found if p not in declared)
    assert not missing, (
        "сервер лениво импортирует эти пакеты, но поставить их неоткуда: %s\n"
        "Объявите их в server/requirements-ai.txt — иначе на машине ВСГУТУ функция "
        "останется выключенной, и причину будет не найти." % missing)


# ─────────────────────────────────────────────────────────────────────────────────
# ОДНА КОМАНДА НА ПЕРЕЕЗД
# ─────────────────────────────────────────────────────────────────────────────────

def test_provisioning_script_exists_and_points_at_the_ai_requirements():
    """Файл с пакетами бесполезен, если его никто не ставит.

    Наш самый частый класс дефекта — «обещание без вызывающего»: функция есть, тесты её
    поведения зелёные, а в продукте её не зовёт никто. Здесь проверяется ВЫЗОВ.
    """
    assert os.path.exists(PROVISION), "tools/provision_ai_host.py пропал"
    text = _read(PROVISION)
    assert "requirements-ai.txt" in text, (
        "скрипт подготовки машины больше не ссылается на requirements-ai.txt — "
        "переезд снова стал ручной операцией")
    assert "install_argos_models" in text, (
        "скрипт перестал ставить модели перевода: пакет приедет, а переводить будет "
        "нечем — ровно тот тихий отказ, ради которого всё это и заведено")
    assert "hostcaps" in text, (
        "скрипт перестал спрашивать о железе — он снова готов поставить тяжёлый набор "
        "на машину, где тот уронит журнал")
