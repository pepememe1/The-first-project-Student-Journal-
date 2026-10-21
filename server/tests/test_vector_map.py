# -*- coding: utf-8 -*-
"""
test_vector_map.py — КАРТА ОТВЕТОВ ВЕКТОРА и свойства, общие для всех ролей.

━━ ЗАЧЕМ ━━
Просьба Ярослава (07.10.2026): «всё обставить тестами в работе Вектора, чтобы проверялась
работа всех его ответов на всех ролях, а также составить карту работы Вектора и его
ответов — чтобы посмотреть на эту карту после обновления и понять, что и как сломалось».

Мир, банк вопросов и сборка карты — `vector_world.py`. Здесь две разные вещи:

  1. КАРТА (`docs/contracts/vector-map.json` и её читаемый вид `VECTOR-MAP.md`) — полный
     снимок: каждый вопрос каждой роли, как он понят и чем отвечено. Тест сверяет живое
     поведение с картой в репозитории и при расхождении ПЕРЕЧИСЛЯЕТ, что изменилось:
     роль, вопрос, поле, было → стало. Намеренное изменение — пересобрать карту
     (`py -3.11 -X utf8 tools/gen_vector_map.py`) и прочитать дифф в git.
     ⚠️ Это снимок значения, и он краснеет на ЛЮБОЙ правке текста ответа — так и
     задумано: карта и есть способ увидеть, что поменялось. Но «просто обновить карту»,
     не читая дифф, — ровно то, от чего она защищает.

  2. СВОЙСТВА, которые от карты не зависят и «обновлением ожидания» не лечатся:
     маршрут ответа по ролям (таблица ниже), чужие данные не показываются, ничего с
     фамилией не уходит модели, одна цифра у всех ролей, числа сходятся с отметками.

Мир строится ОДИН раз на модуль (десяток входов с настоящим хешем пароля), поэтому
фикстура `client` здесь не используется: она пересоздаёт базу на каждый тест.
"""
import io
import json
import os

import pytest
from fastapi.testclient import TestClient

import vector_world as VW

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACTS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "docs", "contracts")
MAP_JSON = os.path.join(CONTRACTS, "vector-map.json")
MAP_MD = os.path.join(CONTRACTS, "VECTOR-MAP.md")
WRITE = os.environ.get("GB_WRITE_VECTOR_MAP") == "1"


@pytest.fixture(scope="module")
def built():
    """Колледж, все входы и готовая карта — один раз на модуль."""
    from conftest import fresh_app_state, HOST_DEVICE_ID
    from app.main import app
    fresh_app_state()
    mp = pytest.MonkeyPatch()
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Device-Id": HOST_DEVICE_ID})
            world = VW.build(client, mp)
            yield {"world": world, "map": VW.build_map(world)}
    finally:
        mp.undo()


def _answers(built, actor: str) -> dict:
    return {a["q"]: a for a in built["map"]["actors"][actor]["answers"]}


def _read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def _write(path: str, text: str) -> None:
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ── 1. карта ──────────────────────────────────────────────────────────────────────────

def _differences(old: dict, new: dict) -> list:
    """Что изменилось между картой в репозитории и живым поведением — человеческими
    строками. Отдельная функция: у неё свой тест (см. ниже) — сверка, которая молчит на
    различии, хуже отсутствующей."""
    out = []
    for key in sorted(set(old.get("actors", {})) | set(new.get("actors", {}))):
        was, now = old.get("actors", {}).get(key), new.get("actors", {}).get(key)
        if was is None or now is None:
            out.append(f"[{key}] роль {'появилась' if was is None else 'пропала'}")
            continue
        a, b = {x["q"]: x for x in was["answers"]}, {x["q"]: x for x in now["answers"]}
        for q in list(a) + [q for q in b if q not in a]:
            if q not in b:
                out.append(f"[{key}] «{q}»: вопрос пропал из карты")
            elif q not in a:
                out.append(f"[{key}] «{q}»: новый вопрос")
            else:
                for field in sorted(set(a[q]) | set(b[q])):
                    if a[q].get(field) != b[q].get(field):
                        out.append(f"[{key}] «{q}» · {field}: "
                                   f"{json.dumps(a[q].get(field), ensure_ascii=False)[:160]} → "
                                   f"{json.dumps(b[q].get(field), ensure_ascii=False)[:160]}")
    if old.get("world") != new.get("world"):
        out.append("изменился сам выдуманный колледж (world)")
    return out


def test_the_map_matches_the_one_in_the_repository(built):
    live = built["map"]
    if WRITE:
        _write(MAP_JSON, VW.dump_json(live))
        _write(MAP_MD, VW.render_md(live))
        n = sum(len(a["answers"]) for a in live["actors"].values())
        print(f"\nкарта записана: {len(live['actors'])} ролей, {n} ответов")
        assert os.path.getsize(MAP_JSON) > 1000
        return
    assert os.path.exists(MAP_JSON), "карты нет — собери: py -3.11 -X utf8 tools/gen_vector_map.py"
    diff = _differences(json.loads(_read(MAP_JSON)), live)
    assert not diff, (
        f"Ответы Вектора разошлись с картой ({len(diff)} отличий). Если правка намеренная — "
        "пересобери карту (py -3.11 -X utf8 tools/gen_vector_map.py) и ПРОЧИТАЙ дифф в git.\n"
        + "\n".join(diff[:40]) + ("\n…" if len(diff) > 40 else ""))


def test_the_readable_map_is_rendered_from_the_same_data(built):
    if WRITE:
        pytest.skip("идёт запись карты")
    assert _read(MAP_MD) == VW.render_md(json.loads(_read(MAP_JSON))), (
        "VECTOR-MAP.md разошёлся с vector-map.json — пересобери обе: tools/gen_vector_map.py")


def test_the_comparison_itself_notices_a_change():
    """Обратный ход для сверки: изменённый текст, изменённый маршрут, пропавший вопрос и
    пропавшая роль — каждое обязано попасть в список отличий."""
    base = {"world": {}, "actors": {"student": {"answers": [
        {"q": "привет", "intent": "hello", "text": "Привет!"},
        {"q": "есть ли долги", "intent": "debtors", "text": "Долгов нет."}]},
        "admin": {"answers": [{"q": "привет", "intent": "hello", "text": "Здравствуйте!"}]}}}
    assert _differences(base, json.loads(json.dumps(base))) == []
    changed = json.loads(json.dumps(base))
    changed["actors"]["student"]["answers"][1]["text"] = "Есть долги."
    changed["actors"]["student"]["answers"][0]["intent"] = "help"
    del changed["actors"]["admin"]
    diff = "\n".join(_differences(base, changed))
    assert "«есть ли долги» · text" in diff and "«привет» · intent" in diff
    assert "[admin] роль пропала" in diff
    shorter = json.loads(json.dumps(base))
    shorter["actors"]["student"]["answers"].pop()
    assert "вопрос пропал из карты" in "\n".join(_differences(base, shorter))


# ── 2. свойства ───────────────────────────────────────────────────────────────────────

KNOWN_INTENTS = None        #заполняется из лексикона — второй список разошёлся бы с ним
MOODS = {"happy", "neutral", "sad", "surprised", "thinking", "worried", "proud", "sleepy"}


def test_every_role_gets_an_answer_to_every_question(built):
    import vector_nlu
    intents = set(vector_nlu.INTENT_STEMS) | {"unknown"}
    total = 0
    for key, actor in built["map"]["actors"].items():
        for a in actor["answers"]:
            total += 1
            where = f"[{key}] «{a['q']}»"
            assert (a.get("text") or "").strip(), f"{where}: пустой ответ"
            if "status" in a:
                assert a["status"] in (403, 404), f"{where}: отказ с кодом {a['status']}"
                continue
            assert a["intent"] in intents, f"{where}: неизвестный интент ответа {a['intent']}"
            assert a["understood"]["intent"] in intents, where
            assert isinstance(a["facts"], dict), where
            for bad in ("[", "укажите", "вставьте", "{", "None", "null"):
                assert bad not in a["text"], f"{where}: в тексте «{bad}»: {a['text'][:120]}"
    assert total >= 300, f"карта подозрительно мала: {total} ответов"


# ── маршрут ответа по ролям: спецификация ─────────────────────────────────────────────
#Вопрос → каким интентом ОБЯЗАН ответить Вектор каждой из шести «полных» ролей. «help» —
#справка либо отказ с причиной; что именно — видно в карте. Таблица написана руками: это
#не снимок, а требование. Правка Вектора, уводящая вопрос в другую ветку, краснеет здесь
#поимённо, и «пересобрать карту» её не лечит.
#   student | teacher (ведёт и курирует) | teacher_subject (только ведёт) | admin |
#   moderator | parent (кабинет ребёнка)
#
#⚠️ ТРИ КЛЕТКИ ЗАПИСАНЫ КАК ЕСТЬ, А НЕ КАК НАДО (найдены картой 07.10.2026, не чинены):
#  • «оценки Сидорова» — человека с такой фамилией нет, и разбор фамилию не видит вовсе
#    (он сверяет слова со списком известных): вопрос отвечается так, будто фамилии не
#    было. Студент получает СВОИ оценки, администратор — сводку. Чужих данных в ответе
#    нет, но человеку не сказано, что такого студента не нашлось;
#  • «что у меня по математике» у преподавателя, который математику не ведёт, — предмет
#    молча отбрасывается, ответ — общая сводка по его группам;
#  • «кто ведет математику» — ответ один на все предметы (весь список преподавателей).
#Чинить — значит менять клетку здесь тем же заходом.
ROUTES = """
привет                      | hello | hello | hello | hello | hello | hello
спасибо                     | thanks | thanks | thanks | thanks | thanks | thanks
что ты умеешь               | help | help | help | help | help | help
как считается средний балл  | howto | howto | howto | howto | howto | howto
расскажи про колледж        | about_college | about_college | about_college | about_college | about_college | about_college
что такое всгуту            | about_vsgutu | about_vsgutu | about_vsgutu | about_vsgutu | about_vsgutu | about_vsgutu
какая погода                | weather | weather | weather | weather | weather | weather
какой у меня средний балл   | average | group_stats | group_stats | group_stats | help | average
покажи мои оценки           | grades | group_stats | group_stats | group_stats | help | grades
что у меня по математике    | subject_grades | subject_grades | group_stats | subject_grades | help | subject_grades
сколько у меня оценок       | grade_count | help | help | help | help | grade_count
сколько оценок по математике | grade_count | help | help | help | help | grade_count
есть ли долги               | debtors | debtors | debtors | debtors | help | debtors
сколько пропусков           | absences | absences | absences | absences | help | absences
что задали                  | homework | homework | homework | homework | help | homework
что задали по математике    | homework | homework | homework | homework | help | homework
какие у меня предметы       | subjects | subjects | subjects | subjects | help | subjects
сколько у меня зет          | zet | help | help | help | help | zet
что нужно до пятёрки по математике | grade_target | grade_target | grade_target | grade_target | grade_target | grade_target
сколько пятёрок нужно       | grade_target | grade_target | grade_target | grade_target | grade_target | grade_target
что сегодня                 | schedule | schedule | schedule | schedule | schedule | schedule
что завтра                  | schedule | schedule | schedule | schedule | schedule | schedule
расписание на среду         | schedule | schedule | schedule | schedule | schedule | schedule
когда физика                | schedule | schedule | schedule | schedule | schedule | schedule
расписание К74/1 на завтра  | schedule | schedule | schedule | schedule | schedule | schedule
расписание К64/2            | schedule | schedule | schedule | schedule | schedule | schedule
какая у меня группа         | groups | groups | groups | groups | help | groups
какие есть группы           | groups | groups | groups | groups | help | groups
кто в группе                | help | roster | roster | roster | help | help
студенты К74/1              | help | roster | roster | roster | help | help
студенты К64/2              | help | help | roster | roster | help | help
кто ведет математику        | teachers | teachers | teachers | teachers | teachers | teachers
преподаватели К74/1         | teachers | teachers | teachers | teachers | teachers | teachers
сводка по группам           | help | group_stats | group_stats | group_stats | help | help
кто в зоне риска            | help | at_risk | at_risk | at_risk | help | help
у кого долги                | debtors | debtors | debtors | debtors | help | debtors
сводка К74/2                | help | group_stats | help | group_stats | help | help
средний балл по физике      | subject_grades | subject_grades | subject_grades | subject_grades | help | subject_grades
что задали К74/1            | homework | homework | homework | homework | help | homework
сколько у нас студентов     | help | group_stats | group_stats | group_stats | help | help
оценки Петрова              | grades | grades | grades | grades | help | help
пропуски Петрова            | absences | absences | absences | absences | help | help
долги Петрова               | debtors | debtors | debtors | debtors | help | help
зет Петрова                 | zet | zet | help | zet | help | help
оценки Ивановой             | help | help | grades | help | help | grades
оценки Ивановой Марии       | help | grades | grades | grades | help | grades
оценки Егорова              | help | help | grades | grades | help | help
оценки Сидорова             | grades | group_stats | group_stats | group_stats | help | grades
что с сервером              | help | help | help | server_state | help | help
расскажи анекдот            | unknown | unknown | unknown | unknown | unknown | unknown
"""
FULL = ["student", "teacher", "teacher_subject", "admin", "moderator", "parent"]
#Роли с коротким набором вопросов — одной строкой: порядок как в `vector_world.SHORT`.
_OWN = ["hello", "help", "average", "grades", "debtors", "schedule", "help", "help", "unknown"]
SHORT_ROUTES = {
    "student_strong": _OWN, "student_new": _OWN,
    "parent_general": _OWN, "parent_two_cabinet": _OWN,
    #Групп нет — на всё, что про группы, объясняет именно это; чужой студент — отказ.
    "teacher_idle": ["hello"] + ["help"] * 7 + ["unknown"],
    #Согласия студента нет / детей несколько — на ЛЮБОЙ вопрос ответ один, с причиной.
    "parent_pending": ["help"] * 9,
    "parent_two": ["help"] * 9,
}


def _routes() -> dict:
    out = {}
    for line in ROUTES.strip().splitlines():
        cells = [c.strip() for c in line.split("|")]
        out[cells[0]] = dict(zip(FULL, cells[1:], strict=True))
    return out


def test_the_route_table_covers_the_whole_question_bank():
    spec = _routes()
    assert list(spec) == VW.QUESTIONS, "таблица маршрутов и банк вопросов разошлись"
    assert all(len(row) == len(FULL) for row in spec.values())
    assert all(len(row) == len(VW.SHORT) for row in SHORT_ROUTES.values())
    assert set(SHORT_ROUTES) | set(FULL) | {"parent_pending_cabinet"} == {a[0] for a in VW.ACTORS}


def test_every_role_is_answered_by_the_intended_branch(built):
    wrong = []
    for q, row in _routes().items():
        for actor, expected in row.items():
            got = _answers(built, actor)[q].get("intent")
            if got != expected:
                wrong.append(f"[{actor}] «{q}»: ждали {expected}, ответ {got}")
    for actor, expected in SHORT_ROUTES.items():
        got = [a.get("intent") for a in built["map"]["actors"][actor]["answers"]]
        if got != expected:
            wrong.append(f"[{actor}] {got} вместо {expected}")
    assert not wrong, "\n".join(wrong)


def test_a_parent_without_consent_is_refused_by_the_child_cabinet(built):
    """Инвариант §4.13: доступ родителя открывает согласие СТУДЕНТА. Кабинет ребёнка без
    согласия — отказ на каждый вопрос, включая «привет», и без единого факта."""
    answers = built["map"]["actors"]["parent_pending_cabinet"]["answers"]
    assert len(answers) == len(VW.SHORT)
    assert all(a.get("status") == 403 and "facts" not in a for a in answers), answers
    #И общая ручка тому же родителю ничего о ребёнке не говорит.
    for a in built["map"]["actors"]["parent_pending"]["answers"]:
        assert a["facts"] == {} and "подтвердит привязку" in a["text"], a


# ── чужие данные и модель ─────────────────────────────────────────────────────────────

def _names(student_ids) -> set:
    """«Имя Отчество» и «Фамилия Имя» перечисленных студентов: по ним видно, что в ответ
    попал именно ЧЕЛОВЕК, а не фамилия, повторённая из вопроса («Студент «Егоров» не в
    ваших группах» — законный отказ, а не утечка)."""
    out = set()
    for sid, surname, name, *_rest in VW.STUDENTS:
        if sid in student_ids:
            out |= {name, f"{surname} {name.split()[0]}"}
    return out


ALL = {s[0] for s in VW.STUDENTS}
#Кого каждая роль видеть НЕ вправе: все студенты минус её область.
HIDDEN = {
    "student": ALL - {"stud:petrov_p"},
    "student_strong": ALL - {"stud:ivanova_m"},
    "student_new": ALL - {"stud:dugarov_b"},
    "parent": ALL - {"stud:ivanova_m"},
    "parent_general": ALL - {"stud:ivanova_m"},
    "parent_two_cabinet": ALL - {"stud:ivanova_o"},
    "parent_pending": ALL, "parent_pending_cabinet": ALL, "parent_two": ALL,
    "moderator": ALL, "teacher_idle": ALL,
    "teacher": {"stud:egorov_e"},                 #ведёт К74/1 и К74/2, курирует К74/1
    "teacher_subject": {"stud:ivanova_o"},        #ведёт К74/1 и К64/2
    "admin": set(),
}


def _leaks(actors: dict, hidden: dict) -> list:
    out = []
    for actor, who in hidden.items():
        for a in actors[actor]["answers"]:
            blob = a["text"] + " " + json.dumps(a.get("facts", {}), ensure_ascii=False)
            out += [f"[{actor}] «{a['q']}»: в ответе «{name}»" for name in sorted(_names(who))
                    if name in blob]
    return out


def test_nobody_is_shown_a_student_outside_their_scope(built):
    """Скоуп по ролям на ВСЁМ банке вопросов: ни в тексте, ни в фактах ответа нет
    студента, которого спрашивающему видеть нельзя. Одна перепутанная выборка — и чужая
    успеваемость на экране; точечный тест поймал бы это только на своём вопросе."""
    assert set(HIDDEN) == {a[0] for a in VW.ACTORS}
    leaks = _leaks(built["map"]["actors"], HIDDEN)
    assert not leaks, "\n".join(leaks)


def test_the_scope_check_can_see_a_leak(built):
    """Обратный ход: та же проверка обязана найти чужих, если ответы администратора
    (ему видны все) выдать за ответы студента."""
    actors = {"student": built["map"]["actors"]["admin"]}
    found = _leaks(actors, {"student": HIDDEN["student"]})
    assert len(found) >= 3, f"проверка утечки слепа: {found}"


def _surnames_in(sent: list) -> list:
    return [f"{kind}: {(text or question)[:90]}" for kind, text, question in sent
            for stem in VW.SURNAME_STEMS
            if stem.lower() in text.lower() or stem.lower() in question.lower()]


def test_nothing_with_a_surname_reaches_the_model(built):
    """🔒 Ни в тексте, ни в вопросе, которые ушли бы модели, нет фамилии человека из
    колледжа — на всех ролях и всех вопросах. Защита ПДн Вектора держится на флаге
    `no_voice` у КАЖДОГО обработчика с именами — это и есть «первое забытое место»."""
    sent = built["world"]["sent"]
    assert len(sent) > 50, f"шпион почти ничего не видел ({len(sent)}) — тест ослеп"
    bad = _surnames_in(sent)
    assert not bad, f"{len(bad)} отправок с фамилией:\n" + "\n".join(bad[:20])
    #Обратный ход: проверка видит фамилию и в тексте, и в вопросе.
    assert _surnames_in([("voice", "Студент Петров Пётр: средний 2.2", "")])
    assert _surnames_in([("voice", "", "оценки Ивановой")])


def test_static_and_administrative_answers_are_never_reworded(built):
    """Статичный текст модель не переписывает (в нём нет цифр — она дописывала
    заглушки), ответы администратору — тоже (она меняла смысл: «в колледже» → «в вашей
    группе»). Свободный разговор — единственное, что уходит модели у администратора."""
    from app.routers.web.vector import _NO_VOICE_INTENTS
    wrong, voiced = [], 0
    for key, actor in built["map"]["actors"].items():
        for a in actor["answers"]:
            if "status" in a:
                continue
            voiced += a["model"] == "voice"
            if a["intent"] == "unknown":
                if a["model"] != "free_chat":
                    wrong.append(f"[{key}] «{a['q']}»: свободный разговор ушёл в {a['model']}")
            elif a["intent"] in _NO_VOICE_INTENTS and a["model"] != "—":
                wrong.append(f"[{key}] «{a['q']}» ({a['intent']}) ушёл в {a['model']}")
            elif key == "admin" and a["model"] != "—":
                wrong.append(f"[admin] «{a['q']}» ушёл в {a['model']}")
    assert not wrong, "\n".join(wrong)
    assert voiced >= 40, f"переформулировок всего {voiced} — шпион модели не работает"


# ── числа: сходятся с отметками и одинаковы у всех ролей ──────────────────────────────

def _expected(student_id: str) -> dict:
    """Средний балл, счёт оценок, часы пропусков и предметы с долгами — НЕЗАВИСИМО от
    продукта, прямо из отметок колледжа. Правила: в средний и в счёт идут практика и ДЗ;
    «Н» в среднем — 2.0; пропуск пары — 2 часа, ДЗ пропуском не бывает."""
    lessons = {lid: (subject, kind) for lid, _g, subject, kind, *_r in VW.LESSONS}
    values, grades, missed, failed = [], [], 0, set()
    for lid, mark in VW.MARKS.get(student_id, {}).items():
        subject, kind = lessons[lid]
        if kind in ("Практика", "ДЗ"):
            values.append(2.0 if mark == "Н" else float(mark))
            if mark != "Н":
                grades.append(mark)
            if mark in ("Н", "2"):
                failed.add(subject)
        if mark == "Н" and kind != "ДЗ":
            missed += 2
    return {"average": round(sum(values) / len(values), 2) if values else 0.0,
            "grades": len(grades), "fives": grades.count("5"), "hours": missed,
            "debt_subjects": len(failed)}


def test_the_debtor_gets_numbers_that_follow_from_his_marks(built):
    mine, want = _answers(built, "student"), _expected("stud:petrov_p")
    assert want == {"average": 2.2, "grades": 2, "fives": 0, "hours": 6, "debt_subjects": 2}
    assert mine["какой у меня средний балл"]["facts"]["average"] == want["average"]
    assert mine["сколько у меня оценок"]["facts"]["всего"] == want["grades"]
    assert mine["сколько пропусков"]["facts"]["всего"] == want["hours"]
    assert mine["есть ли долги"]["facts"]["debts"] == want["debt_subjects"]


def test_homework_grades_are_counted_like_they_are_averaged(built):
    """🔥 Нашла карта (07.10.2026). Оценка за домашнее задание шла в средний балл, а в счёт
    оценок — нет (в счёте стоял литерал «Практика»): «оценок 4» при среднем, выведенном из
    пяти. У отличницы пять оценок: три практики и ДЗ по математике, практика по физике."""
    want = _expected("stud:ivanova_m")
    assert (want["grades"], want["fives"], want["average"]) == (5, 4, 4.8)
    facts = _answers(built, "parent")["сколько у меня оценок"]["facts"]
    assert facts["всего"] == want["grades"] and facts["5"] == want["fives"], facts
    assert _answers(built, "parent")["сколько оценок по математике"]["facts"]["всего"] == 4


def test_one_student_has_one_average_for_every_role(built):
    """Одна цифра на всех экранах: студент, родитель, куратор и администратор видят один
    и тот же средний балл одного и того же человека."""
    petrov = _expected("stud:petrov_p")["average"]
    assert _answers(built, "student")["какой у меня средний балл"]["facts"]["average"] == petrov
    for staff in ("teacher", "admin"):
        assert _answers(built, staff)["оценки Петрова"]["facts"]["average"] == petrov, staff
    ivanova = _expected("stud:ivanova_m")["average"]
    for actor in ("parent", "parent_general", "student_strong"):
        assert _answers(built, actor)["какой у меня средний балл"]["facts"]["average"] == ivanova
    for staff in ("teacher", "admin"):
        assert _answers(built, staff)["оценки Ивановой Марии"]["facts"]["average"] == ivanova, staff
    #Преподаватель без кураторства видит только свой предмет — и цифра у него СВОЯ, по
    #физике. Это не расхождение, а скоуп: проверяем, что она именно по физике.
    assert _answers(built, "teacher_subject")["оценки Петрова"]["facts"]["average"] == 2.0
    assert "Математика" not in _answers(built, "teacher_subject")["оценки Петрова"]["text"]


def test_listed_marks_explain_the_subject_average(built):
    """🔥 Нашла карта. «Средний 2.25. Оценки: 2, 3» — в списке были только практики с
    оценкой, а средний считался ещё и по «Н», и по домашнему заданию: выглядело ошибкой
    арифметики. Свойство: средний из ПЕРЕЧИСЛЕННОГО («Н» — 2.0) равен названному."""
    import re
    checked = 0
    for key, actor in built["map"]["actors"].items():
        for a in actor["answers"]:
            m = re.search(r"средний ([\d.]+)\. Оценки: ([^.]+)\.", a["text"])
            if not m:
                continue
            marks = [2.0 if x.strip() == "Н" else float(x) for x in m.group(2).split(",")]
            assert round(sum(marks) / len(marks), 2) == float(m.group(1)), (key, a["q"], a["text"])
            checked += 1
    assert checked >= 4, f"ответов со списком оценок всего {checked} — тест ослеп"


def test_college_totals_follow_from_the_college(built):
    admin = _answers(built, "admin")
    facts = admin["сводка по группам"]["facts"]
    assert facts["students"] == len(VW.STUDENTS) and facts["groups"] == 3
    assert facts["teachers"] == len(VW.TEACHERS) and facts["parents"] == len(VW.PARENTS)
    roster = admin["студенты К74/1"]
    assert roster["facts"]["count"] == 3
    for who in ("Петров Пётр", "Иванова Мария", "Дугаров Бато"):
        assert who in roster["text"]
    #Преподаватель видит свои группы: Семёнова — К74/1 (3) и К74/2 (1); Орлов — К74/1 и К64/2.
    assert _answers(built, "teacher")["сводка по группам"]["facts"]["students"] == 4
    assert _answers(built, "teacher_subject")["сводка по группам"]["facts"]["students"] == 4
    #Один вопрос — один вид ответа у администратора и преподавателя.
    assert admin["что у меня по математике"]["text"] == \
        _answers(built, "teacher")["что у меня по математике"]["text"]


# ── то, что нашла карта, — под сторожами ──────────────────────────────────────────────

def test_a_parent_gets_the_reason_not_the_help_wall(built):
    """🔥 Нашла карта. Отказ с причиной несёт intent «help», и в кабинете родителя ЛЮБОЙ
    такой ответ подменялся общей справкой: написанное специально для родителя «данные
    других студентов закрыты» до него не доходило ни разу."""
    from app.routers.web.vector import _HELP_BY_ROLE
    for actor in ("parent", "parent_general", "parent_two_cabinet"):
        answers = _answers(built, actor)
        assert answers["что ты умеешь"]["text"] == _HELP_BY_ROLE["parent"]
        for q, a in answers.items():
            if q != "что ты умеешь" and a["intent"] == "help":
                assert a["text"] != _HELP_BY_ROLE["parent"], f"[{actor}] «{q}»: справка вместо причины"
        assert "других студентов закрыты" in answers["оценки Петрова"]["text"]
        assert "администратор" in answers["что с сервером"]["text"]
        #Обращение — к родителю: «твой» в ответах о ребёнке быть не должно.
        for a in answers.values():
            assert "твой" not in a["text"].lower() and "твоя" not in a["text"].lower(), a
    assert "для преподавателя" in _answers(built, "parent")["кто в группе"]["text"]


def test_a_student_without_grades_is_not_told_his_average_is_zero(built):
    a = _answers(built, "student_new")["какой у меня средний балл"]
    assert "0.0" not in a["text"] and "Оценок пока нет" in a["text"], a["text"]
    assert a["facts"]["average"] == 0.0


def test_schedule_speaks_to_staff_and_parents_formally(built):
    """Расписание написано студенту на «ты». Сотруднику и родителю — на «вы»."""
    import re
    informal = re.compile(r"\b(попробуй|назови|посмотри|уточни|спроси)\b", re.I)
    assert informal.search("попробуй чуть позже") and not informal.search("попробуйте чуть позже")
    seen = 0
    for actor in ("teacher", "teacher_subject", "admin", "moderator", "parent",
                  "parent_general", "parent_two_cabinet"):
        for a in built["map"]["actors"][actor]["answers"]:
            if a.get("intent") == "schedule":
                seen += 1
                assert not informal.search(a["text"]), f"[{actor}] «{a['q']}»: {a['text']}"
    assert seen >= 30
    #А студенту — по-прежнему на «ты»: правило про адресата, а не про слово.
    assert "попробуй чуть позже" in _answers(built, "student")["расписание К64/2"]["text"]


def test_schedule_headers_and_groups(built):
    """Три находки карты про расписание: «Срд (Срд)» в заголовке; преподавателю с
    несколькими группами молча показывали первую по алфавиту; модератору на понятый
    вопрос без группы отвечали общей справкой."""
    import re
    twice = re.compile(r"(\w+) \(\1\)")
    assert twice.search("Срд (Срд), II неделя")
    for key, actor in built["map"]["actors"].items():
        for a in actor["answers"]:
            assert not twice.search(a["text"]), f"[{key}] «{a['q']}»: {a['text'][:60]}"
    assert _answers(built, "student")["расписание на среду"]["text"].startswith("Среда (Срд)")
    for actor, groups in (("teacher", (VW.G1, VW.G2)), ("teacher_subject", (VW.G1, VW.G3))):
        text = _answers(built, actor)["что сегодня"]["text"]
        assert all(g in text for g in groups), f"[{actor}] не все группы в ответе: {text}"
    for q in ("что сегодня", "когда физика"):
        assert "Назовите группу" in _answers(built, "moderator")[q]["text"]


def test_hints_and_small_print(built):
    teacher = _answers(built, "teacher")
    assert "«ЗЕТ Иванова»" in teacher["сколько у меня зет"]["text"]
    assert "«сколько оценок у Иванова»" in teacher["сколько у меня оценок"]["text"]
    assert " ч (" in _answers(built, "student")["сколько пропусков"]["text"]
    #Инициалы с портала уже кончаются точкой — второй после них быть не должно.
    for key, actor in built["map"]["actors"].items():
        for a in actor["answers"]:
            assert ".." not in a["text"].replace("…", ""), f"[{key}] «{a['q']}»: {a['text'][-60:]}"
