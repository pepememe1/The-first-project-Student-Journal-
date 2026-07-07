"""
test_ui_invariants.py — Статические инварианты UI, ловящие целый класс регрессий БЕЗ
запуска Qt/GUI (надёжно в CI, детерминированно).

Главный тест родился из реального бага этого проекта: в admin_dashboard._build_pg
потерялась строка `w.setWidget(inner)` → QScrollArea оставался пустым (вкладка пустая),
а `inner` со всеми виджетами оставался без владельца → C++ удалял их → крэш
«Internal C++ object already deleted». Такую ошибку не поймать обычным pytest'ом (это
не синтаксис и не серверная логика), но легко поймать статически по AST.
"""
import ast
import os

_UI = os.path.join(os.path.dirname(__file__), "..", "ui")


def _scrollarea_without_setwidget(source: str) -> list:
    """Возвращает список 'функция: [переменные]' для каждой локальной QScrollArea,
    которой в той же функции ни разу не вызвали .setWidget(...)."""
    tree = ast.parse(source)
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        scroll_vars, setwidget_targets = set(), set()
        for n in ast.walk(fn):
            #  w = QScrollArea()
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func
                fname = getattr(f, "id", None) or getattr(f, "attr", None)
                if fname == "QScrollArea":
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            scroll_vars.add(t.id)
            #  w.setWidget(...)
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "setWidget" and isinstance(n.func.value, ast.Name)):
                setwidget_targets.add(n.func.value.id)
        missing = scroll_vars - setwidget_targets
        if missing:
            offenders.append(f"{fn.name}: {sorted(missing)}")
    return offenders


def test_every_scrollarea_calls_setwidget():
    """Ни одна вкладка-QScrollArea во всех ui/*.py не должна забыть setWidget."""
    problems = []
    for name in os.listdir(_UI):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(_UI, name), encoding="utf-8") as f:
            offenders = _scrollarea_without_setwidget(f.read())
        problems += [f"{name} → {o}" for o in offenders]
    assert not problems, ("QScrollArea без .setWidget(inner) — вкладка будет пустой и "
                          "виджеты удалятся ('C++ object deleted'):\n  " + "\n  ".join(problems))
