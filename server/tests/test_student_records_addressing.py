"""
test_student_records_addressing.py — выборка оценок адресуется студентом, а не его
именем (находка ревью J08, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`webdata.student_records` выбирает оценки по паре (фамилия, имя). У ДВУХ ПОЛНЫХ ТЁЗОК в
одной группе фильтр одинаковый, поэтому каждому показывались оценки обоих — в журнале,
в среднем балле, в отчёте куратора, в ЗЕТ и у родителя. А запись искала студента
`.first()` по тем же двум полям, то есть балл доставался первому найденному.

⚠️ Тёзки в одной группе — редкость, но не выдумка. Цена ошибки здесь несимметрична:
чужая двойка идёт в долги и в индекс риска отчисления.

━━ ЧТО ПРОВЕРЯЕТСЯ ━━
Свойство, а не перечисление: любой вызов `student_records`, у которого ПЕРВЫЕ ДВА
аргумента — это `X.surname` и `X.name` одного объекта, обязан передать `student_id=X.id`.
Такой вызов означает, что объект студента у вызывающего В РУКАХ, и адресовать выборку
именем — уже не вынужденность, а забывчивость. Мест таких два десятка, и перечислить их
списком значило бы завести ещё один список, который однажды разойдётся с кодом.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `student_id=` у любого из вызовов — сторож называет
файл и строку.
"""
import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _calls_without_address():
    bad = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname != "student_records":
                continue
            #Первые два позиционных после db: X.surname, X.name одного и того же X.
            args = node.args[1:3]
            if len(args) < 2:
                continue
            owners = []
            # strict=False НАМЕРЕННО: сверяем только ПЕРВЫЕ два аргумента вызова,
            # у самого вызова их может быть больше или меньше.
            for a, want in zip(args, ("surname", "name"), strict=False):
                if (isinstance(a, ast.Attribute) and a.attr == want
                        and isinstance(a.value, ast.Name)):
                    owners.append(a.value.id)
            if len(owners) != 2 or owners[0] != owners[1]:
                continue        #голые ФИО — вызывающий объекта не имеет, это другой случай
            named = {k.arg for k in node.keywords}
            if "student_id" not in named:
                bad.append(f"{path.relative_to(APP.parent)}:{node.lineno} "
                           f"(объект `{owners[0]}` в руках, а выборка по имени)")
    return bad


def test_every_call_that_has_the_student_addresses_them_by_id():
    bad = _calls_without_address()
    assert not bad, (
        "выборка оценок по ФИО там, где объект студента доступен — у полных тёзок в "
        "группе она отдаст оценки обоих:\n  " + "\n  ".join(bad))


def test_the_guard_itself_can_fail():
    """Обратный ход прямо здесь: сторож обязан замечать дефект, а не только зелёнеть."""
    tree = ast.parse("W.student_records(db, s.surname, s.name, group)\n")
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
    named = {k.arg for k in call.keywords}
    assert "student_id" not in named, "разбор ключевых аргументов сломан"
    owners = [a.value.id for a in call.args[1:3]]
    assert owners == ["s", "s"], "разбор позиционных аргументов сломан"
