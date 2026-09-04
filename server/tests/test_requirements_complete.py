# -*- coding: utf-8 -*-
"""Сторож: всё, что сервер импортирует НА СТАРТЕ, объявлено в requirements.

🔥 Куплено настоящим дефектом (29.08.2026). `server/requirements.txt` не содержал
`requests`, хотя серверный путь его импортирует в трёх местах (парсер портала,
парсер расписания, клиент LLM). На боевой машине пакет стоял СЛУЧАЙНО — приехал
транзитивной зависимостью чего-то другого, — поэтому сервер работал, и заметить
было нечем. Увидел это только чистый CI, где ставят ровно то, что написано:
`ModuleNotFoundError: No module named 'requests'`.

Цена ошибки — не красный CI. Установка на чистую машину ВСГУТУ «по инструкции»
дала бы падение на старте, в чужих руках и в неудобный момент.

⚠️ Проверяем ТОЛЬКО импорты уровня модуля. Это не придирка, а граница смысла:
именно они выполняются при запуске и роняют сервер. Ленивый импорт внутри
функции (`faster_whisper`, `argostranslate`, `sqlcipher3`) — осознанный приём:
нет пакета → функция честно отвечает отказом, а журнал работает. Такие в
requirements могут отсутствовать намеренно, и требовать их значило бы ломать
рабочее решение.

⚠️ И не проверяем список СНИМКОМ. Снимок краснеет на каждом законном добавлении
и учит «просто обновить ожидание» — то есть ровно тому, от чего защищает.
Соответствие «имя импорта → имя пакета» берётся у метаданных установленных
дистрибутивов, а не из таблицы, которую однажды забудут дополнить.
"""

import ast
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_APP = os.path.join(ROOT, "server", "app")
REQUIREMENTS = os.path.join(ROOT, "server", "requirements.txt")


def _python_files(folder):
    for base, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(base, name)


def _local_names():
    """Имена, которые разрешаются В САМОМ РЕПОЗИТОРИИ, а не из venv."""
    names = {"app"}
    for entry in os.listdir(ROOT):
        full = os.path.join(ROOT, entry)
        if entry.endswith(".py"):
            names.add(entry[:-3])
        elif os.path.isdir(full) and os.path.exists(os.path.join(full, "__init__.py")):
            names.add(entry)
    return names


def _module_level_imports(path):
    """Имена верхнего уровня, импортируемые ПРИ ЗАГРУЗКЕ модуля.

    Пропускаем то, что обёрнуто в try/except (осознанно необязательный пакет) и
    в `if TYPE_CHECKING` (для типов, в рантайме не исполняется).
    """
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover — ловит compileall
        return set()

    found = set()
    for node in tree.body:  # ТОЛЬКО верхний уровень: без тел функций и без try
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # относительные — наши
                found.add(node.module.split(".")[0])
    return found


def _server_side_third_party():
    """Сторонние пакеты, нужные серверу на старте."""
    local = _local_names()
    stdlib = set(getattr(sys, "stdlib_module_names", ()))

    files = list(_python_files(SERVER_APP))
    # Корневые общие модули едут на бой вместе с server/app (§8.1) и исполняются
    # в том же процессе — их импорты такие же обязательные.
    for name in sorted(local):
        candidate = os.path.join(ROOT, name + ".py")
        if os.path.exists(candidate):
            files.append(candidate)

    third_party = set()
    for path in files:
        for name in _module_level_imports(path):
            if name in stdlib or name in local or name.startswith("_"):
                continue
            third_party.add(name)
    return third_party


def _declared_distributions():
    """Имена пакетов из requirements.txt, приведённые к сравнимому виду."""
    out = set()
    with open(REQUIREMENTS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[<>=!\[;\s]", line, maxsplit=1)[0].strip()
            if name:
                out.add(_norm(name))
    return out


def _norm(name):
    """PEP 503: разделители и регистр в именах пакетов не значимы."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _distributions_providing(import_name):
    """Какие установленные дистрибутивы дают этот импорт (metadata, не таблица).

    ⚠️ Может вернуть пустоту при ЖИВОМ пакете: `packages_distributions()` строит
    соответствие по `top_level.txt`, а современные колёса его не кладут. Замер на
    Python 3.10.11: из 176 записей `fastapi` и `pydantic` не разрешились, хотя оба
    установлены. Поэтому пустой ответ здесь НЕ считается уликой — вызывающий
    проверяет ещё и совпадение по имени. Сторож, который кричит на исправном
    окружении, перестают читать, и это хуже его отсутствия.
    """
    from importlib import metadata

    try:
        mapping = metadata.packages_distributions()
    except Exception:  # pragma: no cover — метаданные битые, работаем по именам
        return set()
    return {_norm(d) for d in mapping.get(import_name, ())}


def test_server_startup_imports_are_all_declared():
    declared = _declared_distributions()
    assert declared, "requirements.txt разобрался в пустоту — сломан разбор, а не файл"

    missing = []
    for import_name in sorted(_server_side_third_party()):
        providers = _distributions_providing(import_name)
        if providers & declared:
            continue                      # пакет объявлен под своим настоящим именем
        if _norm(import_name) in declared:
            continue                      # объявлен под именем импорта (fastapi и т.п.)
        if providers:
            missing.append(f"{import_name} (даёт пакет {'/'.join(sorted(providers))})")
        else:
            missing.append(f"{import_name} (пакет не объявлен; ставится транзитивно)")

    assert not missing, (
        "сервер импортирует это на старте, но в server/requirements.txt их нет:\n  "
        + "\n  ".join(missing)
        + "\nНа машине разработчика они стоят транзитивно и всё работает; "
        "на чистой установке сервер не поднимется."
    )


def test_the_guard_actually_looks_at_something():
    """Обратный ход: разбор обязан что-то находить.

    Без этого достаточно сломать обход файлов, и предыдущий тест станет вечно
    зелёной заглушкой — форма сторожа, которая уже ловилась у нас трижды.
    """
    found = _server_side_third_party()
    assert "fastapi" in found and "sqlalchemy" in found.union(
        {n.lower() for n in found}
    ), f"разбор импортов сервера сломан, найдено: {sorted(found)[:10]}"


@pytest.mark.parametrize("name", ["requests"])
def test_the_package_that_taught_us_this(name):
    """Именно на нём дефект и поймали — держим дословно."""
    assert _norm(name) in _declared_distributions(), (
        f"{name} снова пропал из server/requirements.txt; "
        "он импортируется на уровне модуля в парсерах и клиенте LLM"
    )


# ─────────────────────────────────────────────────────────────────────────────────
# ВТОРОЙ ИСТОЧНИК ЗАВИСИМОСТЕЙ И ЗАПРЕЩЁННЫЕ ПАКЕТЫ
#
# У нас ДВА объявления зависимостей: `pyproject.toml` (+ замок `uv.lock`, штатный
# путь по документации) и два `requirements.txt` (то, чем реально пользуются CI и
# боевая машина). Пока источников два, они будут расходиться — вопрос только в том,
# заметим ли мы это раньше покупателя.
#
# 🔥 29.08.2026 разошлись оба раза и оба раза в худшую сторону:
#   • `cryptography` объявлена в pyproject и НЕ объявлена серверу, хотя ею
#     шифруются ПДн; держалась на том, что её тянет python-jose[cryptography];
#   • `deep-translator` — клиент к translate.google.com — убран из
#     server/requirements.txt и из venv на бою по 152-ФЗ, а в pyproject и в
#     uv.lock ОСТАЛСЯ. То есть `uv sync --extra server` (команда из нашей же
#     документации) на чистой машине ВСГУТУ вернул бы его обратно, и вместе с ним
#     трансграничную передачу переписки студентов.
# ─────────────────────────────────────────────────────────────────────────────────

#Пакеты, убранные ПО СУЩЕСТВУ, а не по вкусу. Не «не нравятся» — их возвращение
#означает нарушение, поэтому проверяем все места объявления сразу, включая замок.
BANNED = {
    "psycopg2-binary": (
        "драйвер PostgreSQL. База у продукта ОДНА — SQLite (+ SQLCipher на бою); "
        "решение Ярослава 04.09.2026. Поддержка PostgreSQL была ВТОРЫМ, НИ РАЗУ НЕ "
        "ПРОВЕРЕННЫМ путём: на бою всё время работал SQLite (проверено 02.09.2026), "
        "а ветку `is_pg` не покрывал ни один прогон — при этом документация уверенно "
        "писала «на бою PostgreSQL», и по этой неправде строились планы. Возврат "
        "драйвера означает возврат непроверенной ветки — см. server/app/db.py"
    ),
    "psycopg2": (
        "то же, что psycopg2-binary: сборочный вариант того же драйвера PostgreSQL"
    ),
    "asyncpg": (
        "асинхронный драйвер PostgreSQL — та же причина, что у psycopg2"
    ),
    "deep-translator": (
        "HTTP-клиент к translate.google.com: текст личной переписки уходил "
        "иностранному юрлицу целиком. Трансграничная передача (ст. 12 152-ФЗ) и "
        "прямое нарушение п. 5.6.1 политики ВСГУТУ. Заменён локальным Argos "
        "29.08.2026 — см. server/app/translate_service.py"
    ),
}


def _pyproject():
    try:
        import tomllib
    except ImportError:                      # Python 3.10
        import tomli as tomllib
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)


def _heads(items):
    return {_norm(re.split(r"[<>=!\[;\s]", x, maxsplit=1)[0]) for x in items}


def test_pyproject_and_requirements_agree_for_the_server():
    """Два источника обязаны объявлять серверу ОДНО И ТО ЖЕ."""
    data = _pyproject()
    core = _heads(data["project"]["dependencies"])
    extras = data["project"]["optional-dependencies"]
    declared_here = core | _heads(extras["server"])
    #dev-инструменты (pytest и пр.) в requirements сервера допустимы: их ставят
    #ради прогона тестов, к поставке они отношения не имеют.
    dev = _heads(extras.get("dev", []))
    from_requirements = _declared_distributions() - dev

    only_pyproject = sorted(declared_here - from_requirements)
    only_requirements = sorted(from_requirements - declared_here)
    assert not only_pyproject and not only_requirements, (
        "объявления зависимостей сервера разошлись:\n"
        f"  только в pyproject.toml:        {only_pyproject}\n"
        f"  только в requirements.txt:      {only_requirements}\n"
        "Пока источника два, расхождение неизбежно — сведи их в том же заходе."
    )


def test_banned_packages_stay_out_of_every_declaration():
    """Убранный по существу пакет не должен вернуться НИ ОДНИМ из путей."""
    places = {
        "pyproject.toml": open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read(),
        "uv.lock": open(os.path.join(ROOT, "uv.lock"), encoding="utf-8").read(),
        "server/requirements.txt": open(REQUIREMENTS, encoding="utf-8").read(),
        "requirements.txt": open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read(),
    }
    problems = []
    for pkg, why in BANNED.items():
        for where, text in places.items():
            for line in text.splitlines():
                stripped = line.strip()
                #Пояснения ОБЯЗАНЫ упоминать пакет: там написано, почему его убрали.
                #Ищем объявления, а не слова.
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                if pkg in stripped or pkg.replace("-", "_") in stripped:
                    problems.append(f"{where}: {stripped[:80]}  ←  {why}")
    assert not problems, "запрещённый пакет вернулся в объявления:\n  " + "\n  ".join(problems)
