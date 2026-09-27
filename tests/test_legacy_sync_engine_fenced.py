"""
test_legacy_sync_engine_fenced.py — старый движок синка не возвращается в продукт
(исследование синка W-17, 26.09.2026).

`sync/sync_engine.py` выведен из цикла синка 25.09.2026: его push был эхом устаревшего
снимка и откатывал правки, сделанные на сайте (F-03). Файл пока лежит — на нём держатся
старые тесты, — и ровно поэтому опасен: «оживить» его одной строкой импорта легко, а
заметить это по зелёным тестам нельзя (они проверяют сам движок, а не то, что его никто
не зовёт).

Проверяется ОТСУТСТВИЕ импорта во всём продуктовом коде (программа, общие модули,
сервер), разбором `ast`, а не поиском подстроки: упоминание в комментарии или докстринге
импортом не является и продукт не ломает.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `test_fence_sees_a_real_import` подкладывает разбору строку
с настоящим импортом и требует, чтобы ограда её увидела.
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#Где живёт продукт. Тесты, инструменты и сам движок сюда не входят.
PRODUCT_DIRS = ("desktop", "data", "sync", "schedule", os.path.join("server", "app"))
SKIP_FILES = {os.path.join("sync", "sync_engine.py")}


def _imports_engine(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(a.name == "sync.sync_engine" or a.name.endswith(".sync_engine")
                   or a.name == "sync_engine" for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in ("sync.sync_engine", "sync_engine") or mod.endswith(".sync_engine"):
                return True
            if mod == "sync" and any(a.name == "sync_engine" for a in node.names):
                return True
    return False


def _product_files():
    for name in os.listdir(ROOT):
        if name.endswith(".py"):
            yield name
    for d in PRODUCT_DIRS:
        for base, _dirs, files in os.walk(os.path.join(ROOT, d)):
            if "tests" in base.split(os.sep) or "__pycache__" in base:
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.relpath(os.path.join(base, f), ROOT)


def test_product_never_imports_the_retired_sync_engine():
    offenders = []
    for rel in _product_files():
        if rel in SKIP_FILES:
            continue
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            if _imports_engine(fh.read()):
                offenders.append(rel)
    assert not offenders, f"старый движок синка снова импортируется продуктом: {offenders}"


def test_fence_sees_a_real_import():
    assert _imports_engine("from sync import sync_engine\n")
    assert _imports_engine("def f():\n    from sync.sync_engine import reconcile\n")
    assert not _imports_engine('"""упоминание sync_engine в тексте"""\n')
