"""
build_sbom.py — состав программы (SBOM) в формате CycloneDX 1.5.

━━ ЗАЧЕМ ━━
Спросят дважды и в двух разных местах:
  • при поставке ВСГУТУ — «из чего собран продукт, который вы ставите нам на железо»;
  • в заявке в реестр российского ПО (ПП РФ № 1236) — состав зависимостей и
    подтверждение отсутствия ПРИНУДИТЕЛЬНОЙ зависимости от иностранного ПО.
Оба пункта стояли в `docs/PLAN-SALE-AND-MIGRATION.txt` незакрытыми.

━━ ГЛАВНОЕ РЕШЕНИЕ: СОСТАВ ВЫВОДИТСЯ, А НЕ ПЕРЕЧИСЛЯЕТСЯ ━━
🔑 Список берётся из ОБЪЯВЛЕНИЙ (`requirements.txt`, `server/requirements.txt`,
`server/requirements-ai.txt`, `pyproject.toml`) и из `web/package.json`, а не пишется
руками в этом файле.

⚠️ Причина записана кровью в этом проекте. Рукописный список в `build_nuitka.sh`
сопровождался припиской «проверено полным перебором» — она была верна в день написания
и молча устарела, из-за чего собранный .exe не запускался вовсе. Рукописный SBOM
устареет точно так же, но узнаем мы об этом на приёмке, при покупателе.

⚠️ И вторая причина: SBOM, разошедшийся с тем, что реально установлено, ХУЖЕ
отсутствующего. Отсутствие — это «мы не подготовили документ»; расхождение — это
«вы предоставили недостоверные сведения», и разговор становится другим.

━━ ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ ━━
⚠️ Транзитивные зависимости НЕ разворачиваются. Развернуть их честно можно только с
машины, где всё установлено (`importlib.metadata`), а SBOM собирается на машине
разработчика под Windows, где половины боевых пакетов нет by design (sqlcipher3,
faster-whisper). Врать про версии, которых не видели, нельзя — поэтому документ
описывает ПРЯМЫЕ зависимости и честно говорит об этом в поле `notes`.
Полный разворот — на боевой машине: `pip list --format=json`, и тогда `--installed`
дополняет отчёт РЕАЛЬНО установленными версиями.

⚠️ Ни одной зависимости здесь не «оценивается» на юридическую пригодность. Лицензии
берутся из метаданных пакета, если он установлен, и остаются пустыми, если нет.
Проставить лицензию по памяти означало бы выдать догадку за проверенный факт в
документе, который читает юрист.

Запуск:
    python -X utf8 tools/build_sbom.py                 # печатает в stdout
    python -X utf8 tools/build_sbom.py --out sbom.json # пишет файл
    python -X utf8 tools/build_sbom.py --installed     # + версии из этого окружения
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#Файлы объявлений. Порядок значим только для читаемости отчёта.
REQUIREMENTS = (
    ("requirements.txt", "desktop"),
    ("server/requirements.txt", "server"),
    ("server/requirements-ai.txt", "server-ai"),
)

#Имя → зачем оно нам. Пустая строка допустима: назначение необязательно, а выдумывать
#его нельзя. Заполнено для того, что вызывает вопросы на приёмке.
PURPOSE = {
    "gostcrypto": "ГОСТ-этап хеша пароля (Стрибог-512, Р 50.1.111-2016)",
    "sqlcipher3-binary": "шифрование файла базы целиком (AES-256), ПДн at rest",
    "cryptography": "Fernet-шифрование полей ПДн и защита ключей",
    "python-jose": "подпись и проверка JWT",
    "webauthn": "вход по passkey (Face ID / отпечаток)",
    "gigachat": "озвучка ответов Вектора, РОССИЙСКОЕ облако (Сбер)",
    "argostranslate": "перевод сообщений ЛОКАЛЬНО, без передачи текста наружу",
    "faster-whisper": "распознавание речи НА НАШЕЙ машине",
    "openpyxl": "выгрузка журнала в xlsx",
    "python-docx": "выгрузка ведомости в docx",
    "pdfplumber": "разбор учебных планов колледжа (портал отдаёт их PDF)",
}


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].strip()


def _parse_requirement(line: str):
    """Строка requirements → (имя, ограничение версии, маркер) или None.

    ⚠️ Закомментированная строка НЕ является объявлением зависимости — это записка
    человеку с просьбой вспомнить. Инвариант проекта, оплаченный тем, что
    `faster-whisper` и `argostranslate` полгода «были объявлены» и не ставились ничем.
    Поэтому здесь комментарии просто отбрасываются, а не разбираются «на всякий случай».
    """
    text = _strip_comment(line)
    if not text or text.startswith("-"):
        return None
    marker = ""
    if ";" in text:
        text, marker = text.split(";", 1)
        text, marker = text.strip(), marker.strip()
    m = re.match(r"^([A-Za-z0-9._-]+)(\[[^\]]*\])?\s*(.*)$", text)
    if not m:
        return None
    return m.group(1), (m.group(3) or "").strip(), marker


def _declared() -> dict:
    """{имя: {"spec", "marker", "scopes": set}} по всем объявлениям."""
    out: dict = {}
    for rel, scope in REQUIREMENTS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                parsed = _parse_requirement(line)
                if not parsed:
                    continue
                name, spec, marker = parsed
                row = out.setdefault(name.lower(),
                                     {"name": name, "spec": spec, "marker": marker,
                                      "scopes": set()})
                row["scopes"].add(scope)
                if spec and not row["spec"]:
                    row["spec"] = spec
    return out


def _npm() -> list:
    """Прямые зависимости веба из package.json. Без node_modules: их там тысячи, и
    ставятся они только для СБОРКИ — в поставляемый бандл попадает лишь то, что
    сборщик реально включил."""
    path = os.path.join(ROOT, "web", "package.json")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        pkg = json.load(fh)
    rows = []
    for section, scope in (("dependencies", "web"), ("devDependencies", "web-build")):
        for name, spec in (pkg.get(section) or {}).items():
            rows.append({"name": name, "spec": spec, "scope": scope})
    return rows


def _installed_versions() -> dict:
    """Что РЕАЛЬНО стоит в этом окружении (имя → (версия, лицензия))."""
    try:
        from importlib import metadata
    except ImportError:                                   # pragma: no cover
        return {}
    found = {}
    for dist in metadata.distributions():
        try:
            meta = dist.metadata
            name = (meta["Name"] or "").lower()
        except Exception:
            continue
        if not name:
            continue
        lic = meta.get("License") or ""
        if not lic or len(lic) > 80:
            #Часть пакетов кладёт в License весь текст лицензии. Берём классификатор —
            #он короткий и машиночитаемый.
            for c in meta.get_all("Classifier") or []:
                if c.startswith("License ::"):
                    lic = c.rsplit("::", 1)[-1].strip()
                    break
        found[name] = (dist.version or "", lic if len(lic) <= 80 else "")
    return found


def build(with_installed: bool = False) -> dict:
    declared = _declared()
    installed = _installed_versions() if with_installed else {}
    components = []

    for key in sorted(declared):
        row = declared[key]
        ver, lic = installed.get(key, ("", ""))
        comp = {
            "type": "library",
            "name": row["name"],
            "purl": "pkg:pypi/%s" % row["name"].lower(),
            "scope": "required",
            "properties": [
                {"name": "gb:declared_in", "value": ",".join(sorted(row["scopes"]))},
                {"name": "gb:version_spec", "value": row["spec"] or "любая"},
            ],
        }
        if row["marker"]:
            comp["properties"].append({"name": "gb:marker", "value": row["marker"]})
        if PURPOSE.get(key):
            comp["properties"].append({"name": "gb:purpose", "value": PURPOSE[key]})
        if ver:
            comp["version"] = ver
        if lic:
            comp["licenses"] = [{"license": {"name": lic}}]
        components.append(comp)

    for row in _npm():
        components.append({
            "type": "library",
            "name": row["name"],
            "version": row["spec"],
            "purl": "pkg:npm/%s" % row["name"],
            "scope": "required",
            "properties": [{"name": "gb:declared_in", "value": row["scope"]}],
        })

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "component": {
                "type": "application",
                "name": "GradeBookAI",
                "description": ("Электронный журнал успеваемости "
                                "(Технологический колледж ВСГУТУ)"),
            },
            "properties": [
                {"name": "gb:scope",
                 "value": ("ПРЯМЫЕ зависимости из объявлений. Транзитивные не "
                           "разворачиваются: честно перечислить их можно только с "
                           "машины, где всё установлено. Полный состав снимается на "
                           "боевой машине: pip list --format=json")},
                {"name": "gb:versions",
                 "value": ("версии проставлены" if with_installed else
                           "версии НЕ проставлены (запуск без --installed): в "
                           "объявлениях указаны ограничения, а не точные номера")},
                {"name": "gb:foreign_dependency",
                 "value": ("принудительной зависимости от иностранного ПО нет: база "
                           "SQLite, LLM — GigaChat (Сбер, РФ) с офлайн-шаблонами при "
                           "недоступности, перевод и распознавание речи считаются "
                           "локально, сертифицированное СКЗИ подключается при наличии")},
            ],
        },
        "components": components,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Состав программы (CycloneDX 1.5)")
    ap.add_argument("--out", default="", help="куда записать (по умолчанию — stdout)")
    ap.add_argument("--installed", action="store_true",
                    help="дополнить версиями и лицензиями из ЭТОГО окружения")
    args = ap.parse_args()

    doc = build(with_installed=args.installed)
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("SBOM записан: %s (%d компонентов)" % (args.out, len(doc["components"])))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
