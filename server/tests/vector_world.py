# -*- coding: utf-8 -*-
"""
vector_world.py — выдуманный колледж, банк вопросов и сборка КАРТЫ ОТВЕТОВ Вектора.

━━ ЗАЧЕМ ━━
Просьба Ярослава (07.10.2026): «всё обставить тестами в работе Вектора, чтобы проверялась
работа всех его ответов на всех ролях, а также составить карту работы Вектора и его
ответов — чтобы посмотреть на эту карту после обновления и понять, что и как сломалось».

Точечные тесты Вектора проверяют удачную формулировку у одной роли. Ломается обратное:
правка ветки преподавателя меняет ответ куратору, новая основа в лексиконе уводит вопрос
администратора в чужой интент — и увидеть это можно, только задав ВСЕ вопросы ВСЕМ ролям
на одних и тех же данных. Этот модуль — не тест (pytest его не собирает), а общий набор
для `test_vector_map.py` и `tools/gen_vector_map.py`:

  • `build()`      — колледж: три группы, пять студентов (должник, отличница, новичок без
                     оценок, однофамилица в другой группе, студент чужой группы), три
                     преподавателя (ведёт и курирует / только ведёт / без групп), модератор,
                     администратор, три родителя (согласие дано / не дано / двое детей);
  • `QUESTIONS`    — банк вопросов: по живой формулировке на каждый интент лексикона плюс
                     подвохи (фамилия своя, чужая, тёзки, несуществующая; группа своя и чужая);
  • `build_map()`  — задаёт каждый вопрос каждой роли и записывает, как вопрос ПОНЯТ, каким
                     ответом (интент, настроение, факты, текст) и ушёл ли текст модели.

⚠️ ЧТО В КАРТЕ ЗАКРЕПЛЕНО НАРОЧНО, чтобы она не зависела от дня и машины:
  • «сегодня» расписания (`vector._today`) — понедельник `TODAY`;
  • расписание и преподаватели портала ВСГУТУ — подставные (в сеть не ходим);
  • погода — подставная; состояние сервера — заглушка (у каждой машины оно своё, а в
    карте важен маршрут: кому отвечают про сервер, а кому отказывают);
  • модель не вызывается вовсе: шпионы записывают, ЧТО ей ушло бы.
Учебный термин берётся из продукта (`default_term`), а не пишется числом: в текстах
ответов его нет, поэтому карта от календаря не зависит.
"""
import datetime
import json
import types

from conftest import make_admin, assign_teacher
from app.security import hash_password

G1, G2, G3 = "К74/1", "К74/2", "К64/2"
#Понедельник. От этой даты зависят только день недели и чётность недели в расписании.
TODAY = datetime.date(2026, 10, 5)

# id, фамилия, «Имя Отчество», отчество, группа, пароль ('' — войти нельзя и не нужно)
STUDENTS = [
    ("stud:petrov_p", "Петров", "Пётр Андреевич", "Андреевич", G1, "pw-petrov-1"),
    ("stud:ivanova_m", "Иванова", "Мария Сергеевна", "Сергеевна", G1, "pw-ivanova-1"),
    ("stud:dugarov_b", "Дугаров", "Бато Баирович", "Баирович", G1, "pw-dugarov-1"),
    ("stud:ivanova_o", "Иванова", "Ольга Игоревна", "Игоревна", G2, "pw-ivanova-2"),
    ("stud:egorov_e", "Егоров", "Егор Олегович", "Олегович", G3, ""),
]
# id, логин, фамилия, «Имя Отчество», отчество, предметы, курирует
TEACHERS = [
    ("teach:semenova", "semenova", "Семёнова", "Анна Петровна", "Петровна", ["Математика"], [G1]),
    ("teach:orlov", "orlov", "Орлов", "Игорь Васильевич", "Васильевич", ["Физика"], []),
    ("teach:novikov", "novikov", "Новиков", "Олег Иванович", "Иванович", [], []),
]
ASSIGNMENTS = [("teach:semenova", G1, "Математика"), ("teach:semenova", G2, "Математика"),
               ("teach:orlov", G1, "Физика"), ("teach:orlov", G3, "Физика")]
GROUP_SUBJECTS = {G1: ["Математика", "Физика", "История"], G2: ["Математика"], G3: ["Физика"]}
# логин, фамилия, «Имя Отчество», дети (id студента, дал ли студент согласие)
PARENTS = [
    ("sokolova", "Соколова", "Ольга Николаевна", [("stud:ivanova_m", True)]),
    ("petrova", "Петрова", "Нина Ивановна", [("stud:petrov_p", False)]),
    ("kuznetsova", "Кузнецова", "Вера Павловна", [("stud:ivanova_m", True), ("stud:ivanova_o", True)]),
]
# id, группа, предмет, тип, номер, тема, дата
LESSONS = [
    ("ml1", G1, "Математика", "Лекция", 1, "Введение в анализ", "01.09.2026"),
    ("m1", G1, "Математика", "Практика", 1, "Пределы", "07.09.2026"),
    ("m2", G1, "Математика", "Практика", 2, "Производные", "14.09.2026"),
    ("m3", G1, "Математика", "Практика", 3, "Интегралы", "21.09.2026"),
    ("mh1", G1, "Математика", "ДЗ", 1, "Задачи 1–10 на странице 45", "22.09.2026"),
    ("f1", G1, "Физика", "Практика", 1, "Кинематика", "08.09.2026"),
    ("n1", G2, "Математика", "Практика", 1, "Пределы", "07.09.2026"),
    ("n2", G2, "Математика", "Практика", 2, "Производные", "14.09.2026"),
    ("p1", G3, "Физика", "Практика", 1, "Кинематика", "09.09.2026"),
]
#Отметки. Петров — должник и прогульщик, Иванова Мария — отличница, у Дугарова оценок нет.
MARKS = {
    "stud:petrov_p": {"ml1": "Н", "m1": "2", "m2": "Н", "m3": "3", "mh1": "Н", "f1": "Н"},
    "stud:ivanova_m": {"m1": "5", "m2": "5", "m3": "4", "mh1": "5", "f1": "5"},
    "stud:ivanova_o": {"n1": "4", "n2": "4"},
    "stud:egorov_e": {"p1": "3"},
}
#Расписание К74/1 «с портала»: две недели, чтобы «когда физика» и чётность было видно.
SCHEDULE = {G1: {"group": G1, "weeks": {
    "1": {"Пнд": [{"pair_no": 1, "time": "08:00–09:35", "subject": "Математика", "room": "301"},
                  {"pair_no": 2, "time": "09:45–11:20", "subject": "Физика", "room": "214"}],
          "Втр": [{"pair_no": 1, "time": "08:00–09:35", "subject": "История", "room": "105"}]},
    "2": {"Пнд": [{"pair_no": 2, "time": "09:45–11:20", "subject": "Математика", "room": "301"}],
          "Срд": [{"pair_no": 3, "time": "11:30–13:05", "subject": "Физика", "room": "214"}]},
}}}
#Кого называет расписание портала: двое с учётной записью и один без неё.
PORTAL_TEACHERS = {G1: [("Математика", "СЕМЁНОВА А.П."), ("Физика", "ОРЛОВ И.В."),
                        ("История", "ПОРТАЛОВ П.П.")]}

# ── банк вопросов ─────────────────────────────────────────────────────────────────────
QUESTIONS = [
    # общее и статичное
    "привет", "спасибо", "что ты умеешь", "как считается средний балл",
    "расскажи про колледж", "что такое всгуту", "какая погода",
    # своя успеваемость
    "какой у меня средний балл", "покажи мои оценки", "что у меня по математике",
    "сколько у меня оценок", "сколько оценок по математике", "есть ли долги",
    "сколько пропусков", "что задали", "что задали по математике",
    "какие у меня предметы", "сколько у меня зет",
    # расписание
    "что сегодня", "что завтра", "расписание на среду", "когда физика",
    "расписание К74/1 на завтра", "расписание К64/2",
    # справочники
    "какая у меня группа", "какие есть группы", "кто в группе", "студенты К74/1",
    "студенты К64/2", "кто ведет математику", "преподаватели К74/1",
    # сводки
    "сводка по группам", "кто в зоне риска", "у кого долги", "сводка К74/2",
    "средний балл по физике", "что задали К74/1", "сколько у нас студентов",
    # о конкретном человеке: свой, тёзки, уточнённый именем, чужой, несуществующий
    "оценки Петрова", "пропуски Петрова", "долги Петрова", "зет Петрова",
    "оценки Ивановой", "оценки Ивановой Марии", "оценки Егорова", "оценки Сидорова",
    # сервер и свободный разговор
    "что с сервером", "расскажи анекдот",
]
#Короткий набор — для ролей, чей ответ почти всегда один и тот же отказ или справка.
SHORT = ["привет", "что ты умеешь", "какой у меня средний балл", "покажи мои оценки",
         "есть ли долги", "что сегодня", "оценки Петрова", "что с сервером", "расскажи анекдот"]

# ключ, подпись, дверь ('ask' — общая ручка, 'parent' — кабинет родителя), логин,
# id ребёнка для кабинета родителя, чьими глазами разбирается вопрос, набор вопросов
ACTORS = [
    ("student", "Студент-должник — Петров Пётр, К74/1", "ask", "petrov_p", "", "petrov_p", QUESTIONS),
    ("teacher", "Преподаватель — Семёнова: ведёт математику в К74/1 и К74/2, курирует К74/1",
     "ask", "semenova", "", "semenova", QUESTIONS),
    ("teacher_subject", "Преподаватель без кураторства — Орлов: физика в К74/1 и К64/2",
     "ask", "orlov", "", "orlov", QUESTIONS),
    ("admin", "Администратор", "ask", "admin", "", "admin", QUESTIONS),
    ("moderator", "Модератор", "ask", "moderov", "", "moderov", QUESTIONS),
    ("parent", "Родитель в кабинете ребёнка — Соколова, ребёнок Иванова Мария (согласие дано)",
     "parent", "sokolova", "stud:ivanova_m", "ivanova_m", QUESTIONS),
    ("student_strong", "Студентка-отличница — Иванова Мария, К74/1", "ask", "ivanova_m", "",
     "ivanova_m", SHORT),
    ("student_new", "Студент без единой оценки — Дугаров Бато, К74/1", "ask", "dugarov_b", "",
     "dugarov_b", SHORT),
    ("teacher_idle", "Преподаватель без групп — Новиков", "ask", "novikov", "", "novikov", SHORT),
    ("parent_general", "Родитель через общую ручку и команду /vector — Соколова (один ребёнок)",
     "ask", "sokolova", "", "ivanova_m", SHORT),
    ("parent_pending", "Родитель без согласия студента, общая ручка — Петрова",
     "ask", "petrova", "", "petrova", SHORT),
    ("parent_pending_cabinet", "Родитель без согласия студента, кабинет ребёнка — Петрова",
     "parent", "petrova", "stud:petrov_p", "petrova", SHORT),
    ("parent_two", "Родитель двоих детей, общая ручка — Кузнецова",
     "ask", "kuznetsova", "", "kuznetsova", SHORT),
    ("parent_two_cabinet", "Родитель двоих детей в кабинете второго ребёнка — Кузнецова, "
     "ребёнок Иванова Ольга", "parent", "kuznetsova", "stud:ivanova_o", "ivanova_o", SHORT),
]

#Фамилии всех людей колледжа — для проверки «в модель не ушло ни одной» (без окончаний:
#«Петров» ловит и «Петрова», и «Петрову»).
SURNAME_STEMS = ["Петров", "Иванов", "Дугаров", "Егоров", "Семёнов", "Семенов", "Орлов",
                 "Новиков", "Соколов", "Кузнецов", "Модеров"]


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, (login, r.text)
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def install_fakes(mp) -> list:
    """Подставить всё, что зависит от дня, сети и машины. Возвращает список, куда шпионы
    складывают отправленное модели: (чем, текст, вопрос)."""
    from app import schedule_web, vector_llm
    from app.routers.web import vector as V
    import weather

    sent = []

    def voice(cfg, facts_text, role="student", question="", locale="ru"):
        sent.append(("voice", facts_text, question))
        return facts_text

    def free_chat(cfg, question, role="student", context="", locale="ru"):
        sent.append(("free_chat", "", question))
        return "«свободный разговор: отвечает модель»"

    def complete(*args, **kwargs):
        sent.append(("complete", " ".join(str(a) for a in args[1:]), ""))
        return ""

    mp.setattr(vector_llm, "voice", voice)
    mp.setattr(vector_llm, "free_chat", free_chat)
    if hasattr(vector_llm, "complete"):
        mp.setattr(vector_llm, "complete", complete)
    mp.setattr(V, "_today", lambda: TODAY)
    mp.setattr(schedule_web, "get_group",
               lambda group, category="", **kw: json.loads(json.dumps(SCHEDULE.get(group))))
    lesson = lambda subject, teacher: types.SimpleNamespace(subject=subject, teacher=teacher)  # noqa: E731
    snap = types.SimpleNamespace(groups={
        g: types.SimpleNamespace(all_lessons=lambda rows=rows: [
            (1, "Пнд", lesson(s, t)) for s, t in rows])
        for g, rows in PORTAL_TEACHERS.items()})
    mp.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    mp.setattr(weather, "_fetch", lambda: {"temp": -5, "feels": -9, "wind": 4, "code": 3})
    weather._cache.update({"at": 0.0, "data": None})
    mp.setattr(V, "_server_state_facts", lambda db: {
        "text": "Сервер: состояние машины в карту не входит — у каждой оно своё.",
        "mood": "neutral", "intent": "server_state", "facts": {"source": "карта"},
        "no_voice": True})
    return sent


def build(client, mp) -> dict:
    """Завести колледж и войти всеми действующими лицами. Возвращает «мир»."""
    from app.db import default_term
    sent = install_fakes(mp)
    ty, ts = default_term()
    admin = make_admin(client)
    users = [{"id": sid, "role": "student", "login": sid.split(":")[1], "surname": f, "name": n,
              "patronymic": p, "full_name": "", "group_name": g,
              "password_hash": hash_password(pw) if pw else ""}
             for sid, f, n, p, g, pw in STUDENTS]
    users += [{"id": tid, "role": "teacher", "login": login, "surname": f, "name": n,
               "patronymic": p, "full_name": f"{f} {n}", "subjects": subj,
               "curated_groups": cur, "password_hash": hash_password(f"pw-{login}-1")}
              for tid, login, f, n, p, subj, cur in TEACHERS]
    users.append({"id": "mod:moderov", "role": "moderator", "login": "moderov",
                  "surname": "Модеров", "name": "Матвей Олегович", "patronymic": "Олегович",
                  "full_name": "Модеров Матвей Олегович",
                  "password_hash": hash_password("pw-moderov-1")})
    people = {sid: (f, n) for sid, f, n, _p, _g, _pw in STUDENTS}
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": f"grp:{i}", "name": g, "subjects": subj}
                   for i, (g, subj) in enumerate(GROUP_SUBJECTS.items(), 1)],
        "users": users,
        "lessons": [{"id": lid, "group_name": g, "subject": s, "type": t, "number": n,
                     "topic": topic, "date": date, "year": ty, "semester": ts}
                    for lid, g, s, t, n, topic, date in LESSONS],
        "grades": [{"id": f"{sid}|{lid}", "student_id": sid, "student_f": people[sid][0],
                    "student_n": people[sid][1], "lesson_id": lid, "grade": mark}
                   for sid, marks in MARKS.items() for lid, mark in marks.items()],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    #Каталог предметов — своей ручкой (синк его не принимает): по нему администратор
    #опознаёт предмет в вопросе.
    for name in sorted({s for subj in GROUP_SUBJECTS.values() for s in subj}):
        r = client.post("/web/admin/subjects", json={"name": name}, headers=admin)
        assert r.status_code == 200, r.text
    for tid, group, subject in ASSIGNMENTS:
        assign_teacher(client, admin, tid, group, subject, year=ty, semester=ts)

    headers = {"admin": admin, "moderov": _login(client, "moderov", "pw-moderov-1")}
    for sid, _f, _n, _p, _g, pw in STUDENTS:
        if pw:
            headers[sid.split(":")[1]] = _login(client, sid.split(":")[1], pw)
    for _tid, login, *_rest in TEACHERS:
        headers[login] = _login(client, login, f"pw-{login}-1")
    for login, surname, name, kids in PARENTS:
        r = client.post("/web/admin/parents", headers=admin, json={
            "login": login, "surname": surname, "name": name, "password": f"pw-{login}-1"})
        assert r.status_code == 200, r.text
        parent_id = r.json()["id"]
        for student_id, approved in kids:
            r = client.post("/web/staff/parent-links", headers=admin,
                            json={"parent_id": parent_id, "student_id": student_id})
            assert r.status_code == 200, r.text
            if approved:
                r = client.post(f"/web/student/parent-links/{r.json()['id']}/decide",
                                json={"approve": True}, headers=headers[student_id.split(":")[1]])
                assert r.status_code == 200, r.text
        headers[login] = _login(client, login, f"pw-{login}-1")
    return {"client": client, "headers": headers, "sent": sent, "term": (ty, ts)}


def _understood(world, login: str, question: str) -> dict:
    """Как вопрос ПОНЯТ — тем же разбором и с теми же списками, что берёт сам Вектор."""
    import vector_nlu
    from app.db import SessionLocal
    from app.models import User
    from app.routers.web import vector as V
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.login == login).first()
        nlu = vector_nlu.classify(question.lower(), surnames=V._known_surnames(user, db),
                                  subjects=V._known_subjects(user, db),
                                  groups=V._group_names(db))
    finally:
        db.close()
    out = {"intent": nlu["intent"]}
    for key in ("subject", "surname", "group"):
        if nlu.get(key):
            out[key] = nlu[key]
    if nlu.get("day") not in ("", None):
        out["day"] = nlu["day"]
    return out


def ask(world, actor: tuple, question: str) -> dict:
    """Один вопрос одной роли → строка карты."""
    _key, _label, door, login, child, nlu_login, _bank = actor
    client, sent = world["client"], world["sent"]
    mark = len(sent)
    if door == "parent":
        r = client.post("/web/parent/vector/ask", headers=world["headers"][login],
                        json={"message": question, "student_id": child})
    else:
        r = client.post("/web/vector/ask", headers=world["headers"][login],
                        json={"message": question})
    entry = {"q": question, "understood": _understood(world, nlu_login, question)}
    if r.status_code != 200:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith(
            "application/json") else r.text
        entry.update({"status": r.status_code, "text": str(detail)})
        return entry
    body = r.json()
    kinds = sorted({kind for kind, _text, _q in sent[mark:]})
    entry.update({"intent": body.get("intent"), "mood": body.get("mood"),
                  "model": "+".join(kinds) if kinds else "—",
                  "facts": {k: v for k, v in (body.get("facts") or {}).items()},
                  "text": body.get("text", "")})
    return entry


def build_map(world) -> dict:
    """Задать каждый вопрос каждой роли. Порядок — как в `ACTORS` и в банке вопросов."""
    return {
        "_": ("КАРТА ОТВЕТОВ ВЕКТОРА. Файл собирается из кода, руками не правится: "
              "`py -3.11 -X utf8 tools/gen_vector_map.py`. Каждая строка — вопрос одной роли "
              "на выдуманном колледже (`server/tests/vector_world.py`): как вопрос понят "
              "(understood), чем отвечено (intent, mood, facts, text) и ушёл ли текст модели "
              "(model: voice — переформулировка, free_chat — свободный разговор, «—» — ответ "
              "отдан как есть). После правки Вектора пересобери карту и прочитай дифф: он и "
              "покажет, что и у какой роли изменилось."),
        "world": {
            "today": TODAY.isoformat() + " (понедельник, закреплено)",
            "groups": {g: {"subjects": GROUP_SUBJECTS[g],
                           "students": [f"{f} {n}" for _sid, f, n, _p, grp, _pw in STUDENTS
                                        if grp == g]} for g in (G1, G2, G3)},
            "marks": {next(f"{f} {n}" for sid, f, n, *_r in STUDENTS if sid == who): marks
                      for who, marks in MARKS.items()},
            "lessons": {lid: f"{g} · {s} · {t} №{n} · {date}"
                        for lid, g, s, t, n, _topic, date in LESSONS},
        },
        "actors": {actor[0]: {"who": actor[1],
                              "door": "/web/parent/vector/ask" if actor[2] == "parent"
                              else "/web/vector/ask",
                              "answers": [ask(world, actor, q) for q in actor[6]]}
                   for actor in ACTORS},
    }


def dump_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def render_md(data: dict) -> str:
    """Карта для чтения глазами: по таблице на роль. Собирается из той же карты, что и
    JSON, — разойтись они не могут (это проверяет тест)."""
    def cell(text, limit=0):
        s = str(text).replace("\n", " ⏎ ").replace("|", "¦")
        return s if not limit or len(s) <= limit else s[:limit - 1] + "…"

    out = ["# Карта ответов Вектора", "",
           "> Собирается из кода: `py -3.11 -X utf8 tools/gen_vector_map.py`. Руками не править.",
           "> Полные тексты и факты — в `vector-map.json` рядом; здесь текст обрезан.",
           "> Колледж выдуманный (`server/tests/vector_world.py`), «сегодня» — "
           + data["world"]["today"] + ".", "",
           "Как читать: «понят как» — что разобрал классификатор; «ответ» — интент и настроение "
           "ответа; «модель» — ушёл ли текст на переформулировку (`voice`), в свободный "
           "разговор (`free_chat`) или отдан как есть (`—`).", "", "## Колледж", ""]
    for group, info in data["world"]["groups"].items():
        out.append(f"- **{group}** — предметы: {', '.join(info['subjects'])}; студенты: "
                   f"{', '.join(info['students'])}")
    out.append("")
    for who, marks in data["world"]["marks"].items():
        out.append(f"- {who}: " + ", ".join(f"{data['world']['lessons'][lid]} → «{m}»"
                                            for lid, m in marks.items()))
    for key, actor in data["actors"].items():
        out += ["", f"## {actor['who']}", "", f"`{key}` · ручка `{actor['door']}`", "",
                "| № | Вопрос | Понят как | Ответ | Модель | Текст |",
                "|---|---|---|---|---|---|"]
        for i, a in enumerate(actor["answers"], 1):
            u = a["understood"]
            understood = u["intent"] + "".join(
                f" · {k}={u[k]}" for k in ("subject", "surname", "group", "day") if k in u)
            if "status" in a:
                answer, model = f"отказ {a['status']}", "—"
            else:
                answer, model = f"{a['intent']} · {a['mood']}", a["model"]
            out.append(f"| {i} | {cell(a['q'])} | {cell(understood)} | {cell(answer)} | "
                       f"{cell(model)} | {cell(a['text'], 170)} |")
    return "\n".join(out) + "\n"
