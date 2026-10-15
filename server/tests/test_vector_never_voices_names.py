"""
test_vector_never_voices_names.py — 🔒 ФАМИЛИИ ЛЮДЕЙ НЕ УХОДЯТ В LLM. НИКОГДА.

━━ ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ ━━
Прежний конвейер Вектора обещал `privacy.anonymize()` — обезличивание ФИО перед отправкой
в модель и обратную подстановку после. Такого шага НЕТ: пакет `vector/` удалён 15.08.2026,
а вместо анонимизации принято решение проще и строже — **ответы, содержащие имена, вообще
не идут в LLM**. Обработчик выставляет `no_voice`, и `answer_vector_question` отдаёт текст
как есть (плюс статический `_NO_VOICE_INTENTS`).

Решение верное, но у него цена любого флага: **его можно забыть**. Защита держится на том,
что КАЖДЫЙ из полутора десятков обработчиков, возвращающих фамилии, выставил `no_voice` —
а это ровно наш класс дефекта «первое забытое место». Забытый флаг не ломает ничего
видимого: ответ придёт, будет выглядеть правдоподобно, и только ФИО студентов колледжа
уедут в GigaChat вместе с их оценками и долгами. Заметить это можно лишь чтением кода
конкретного обработчика, то есть никогда.

Здесь проверяется СВОЙСТВО, а не список интентов: подменяем `vector_llm.voice`
перехватчиком и требуем, чтобы НИ В ОДНОМ переданном ему тексте не встретилась фамилия
живого пользователя из справочника. Новый интент, забывший флаг, покраснеет сам, без
единой правки этого файла.

⚠️ Почему нельзя ограничиться `_NO_VOICE_INTENTS`: он статический и покрывает интенты,
где имён нет по построению (привет, справка, расписание). Имена возвращают СОВСЕМ другие
ветки — должники, состав группы, риск отчисления, «кто ведёт предмет», — и там флаг
динамический.
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher
from app.security import hash_password


#Фамилии нарочно редкие и непохожие на обычные слова: подстрока «Иванов» встретилась бы
#в тексте случайно, и тест ловил бы собственную выдумку, а не утечку.
SURNAMES = ["Цыдыпов", "Жамбалдоржиев", "Очирнимаев"]


@pytest.fixture()
def world(client):
    """Группа с тремя студентами, у двоих — долги (двойка и неявка).

    Долги нужны обязательно: именно ответы про должников и про риск отчисления
    возвращают ФИО, и именно они интересны LLM «для красоты формулировки».
    """
    admin = make_admin(client)
    users, grades = [], []
    for i, surname in enumerate(SURNAMES, start=1):
        users.append({"id": f"stud:s{i}", "role": "student", "login": f"s{i}",
                      "password_hash": hash_password("studpass1"), "surname": surname,
                      "name": "Батор", "group_name": "ИС-21"})
    #Двойка первому и неявка второму — оба попадают в списки, где называются имена.
    grades.append({"id": "g1", "student_f": SURNAMES[0], "student_n": "Батор",
                   "lesson_id": "L1", "grade": "2"})
    grades.append({"id": "g2", "student_f": SURNAMES[1], "student_n": "Батор",
                   "lesson_id": "L1", "grade": "Н"})
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "g:ИС-21", "name": "ИС-21", "subjects": ["Математика"]}],
        "users": users,
        "lessons": [{"id": "L1", "group_name": "ИС-21", "subject": "Математика",
                     "type": "Практика", "number": 1, "topic": "т",
                     "date": "01.09.2025"},
                    {"id": "E1", "group_name": "ИС-21", "subject": "Математика",
                     "type": "Экзамен", "number": 1, "topic": "т",
                     "date": "20.12.2025"}],
        "grades": grades}}, headers=admin)
    assert r.status_code == 200, r.text
    teacher = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    return {"admin": admin, "teacher": teacher, "client": client}


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


#Вопросы, которые СПОСОБНЫ вернуть имена. Список нарочно шире того, что возвращает их
#сегодня: цель — поймать день, когда новый обработчик начнёт их возвращать.
QUESTIONS = [
    "у кого долги",
    "кто должник",
    "кто в зоне риска",
    "состав группы ИС-21",
    "покажи список студентов",
    "сколько студентов",
    "у кого пропуски",
    "статистика группы ИС-21",
    "средний балл группы ИС-21",
    "кто ведёт математику",
    "какие у меня группы",
    "какие предметы у ИС-21",
    "успеваемость группы",
    "кто не сдал экзамен",
    #🔥 Фамилия в САМОМ ВОПРОСЕ (возражение Полковника 29.09.2026): вопрос уходит в
    #модель дословно вместе с фактами, и «ЗЕТ Цыдыпова» отдавал фамилию наружу, хотя
    #текст ответа был чистым.
    "ЗЕТ Цыдыпова",
    "сводка Цыдыпов",
    "сколько оценок у Цыдыпова",
]


def _sent_to_llm(monkeypatch):
    """Подменяет озвучку перехватчиком и возвращает список того, что в неё уехало."""
    from app import vector_llm
    seen = []

    def _spy(cfg, facts_text, role="student", question="", locale="ru"):
        #И факты, И вопрос: вопрос попадает в промпт модели дословно (vector_llm.voice).
        seen.append(facts_text)
        seen.append(question)
        return facts_text

    #Свободный разговор и перевод ответа — тоже дорога к модели (находка Полковника
    #14.10.2026: шпион видел только озвучку, и утечка по этим двум путям прошла бы мимо).
    def _spy_chat(cfg, question, role="student", context="", locale="ru"):
        seen.append(question)
        seen.append(context)
        return "ok"

    def _spy_complete(cfg, messages, temperature=0.3):
        for m in messages or []:
            seen.append(str((m or {}).get("content", "")))
        return ""

    monkeypatch.setattr(vector_llm, "voice", _spy)
    monkeypatch.setattr(vector_llm, "free_chat", _spy_chat)
    monkeypatch.setattr(vector_llm, "complete", _spy_complete)
    return seen


def _assert_clean(seen):
    for text in seen:
        for surname in SURNAMES:
            assert surname not in text, (
                f"ФАМИЛИЯ «{surname}» УЕХАЛА В LLM.\n"
                f"Текст: {text[:300]}\n"
                "Обработчик, вернувший этот ответ, забыл выставить no_voice=True. "
                "Это не косметика: имена студентов колледжа вместе с их оценками "
                "уходят внешнему сервису, и заметить это можно только здесь."
            )


def test_teacher_answers_with_names_never_reach_the_model(world, monkeypatch):
    """🔥 ГЛАВНОЕ. Преподаватель — та роль, которой Вектор ЗАКОННО называет фамилии
    (он видит своих студентов в журнале). Значит именно у него больше всего ответов,
    где флаг можно забыть.

    Обратный ход проверен: убрать `no_voice` у обработчика долгов — тест краснеет,
    называя и фамилию, и текст."""
    seen = _sent_to_llm(monkeypatch)
    headers = world["teacher"]
    for q in QUESTIONS:
        r = world["client"].post("/web/vector/ask", json={"message": q}, headers=headers)
        assert r.status_code == 200, (q, r.text)
    _assert_clean(seen)


def test_admin_answers_with_names_never_reach_the_model(world, monkeypatch):
    """Админ видит справочники целиком — у него списки людей самые длинные."""
    seen = _sent_to_llm(monkeypatch)
    headers = world["admin"]
    for q in QUESTIONS:
        r = world["client"].post("/web/vector/ask", json={"message": q}, headers=headers)
        assert r.status_code == 200, (q, r.text)
    _assert_clean(seen)


def test_student_answers_never_carry_a_classmate_name(world, monkeypatch):
    """У студента скоуп «только о себе», и фамилий одногруппников он получать не должен
    ВООБЩЕ — ни в ответе, ни тем более в модели. Проверяем оба конца сразу."""
    seen = _sent_to_llm(monkeypatch)
    headers = _login(world["client"], "s1", "studpass1")
    for q in QUESTIONS:
        r = world["client"].post("/web/vector/ask", json={"message": q}, headers=headers)
        assert r.status_code == 200, (q, r.text)
        #Чужая фамилия не должна встретиться даже в ответе САМОМУ студенту.
        for surname in SURNAMES[1:]:
            assert surname not in r.json().get("text", ""), (q, surname)
    _assert_clean(seen)


def test_the_guard_can_actually_fail(world, monkeypatch):
    """🔒 ОБРАТНЫЙ ХОД САМОГО СТОРОЖА. Проверка, которая не может покраснеть, неотличима
    от исправного кода — у нас это ловилось трижды. Здесь мы ЛОМАЕМ продукт нарочно:
    заставляем `answer_vector_question` игнорировать флаг `no_voice`, и требуем, чтобы
    проверка это заметила.

    Если этот тест когда-нибудь станет зелёным «сам собой» — значит либо ответы перестали
    содержать фамилии (тогда перепишите список вопросов), либо сторож выше проверяет не
    то, и на него больше нельзя полагаться."""
    from app.routers.web import vector as V

    seen = _sent_to_llm(monkeypatch)
    #Пустой набор статических интентов + затёртый динамический флаг = озвучиваем ВСЁ.
    monkeypatch.setattr(V, "_NO_VOICE_INTENTS", set())
    original = V._vector_facts

    def _no_flag(*a, **kw):
        result = original(*a, **kw)
        if isinstance(result, dict):
            result.pop("no_voice", None)
        return result

    monkeypatch.setattr(V, "_vector_facts", _no_flag)

    headers = world["teacher"]
    for q in QUESTIONS:
        world["client"].post("/web/vector/ask", json={"message": q}, headers=headers)

    leaked = [t for t in seen if any(s in t for s in SURNAMES)]
    assert leaked, (
        "Сломанный продукт не был замечен: ни одна фамилия не уехала в LLM даже когда "
        "флаг no_voice отключён целиком. Значит сторож выше проверяет не тот путь."
    )


# ── Вторая линия защиты на /vector/voice и короткие фамилии (15.10.2026) ─────────────
def test_voice_endpoint_does_not_pass_names_to_the_model(world, monkeypatch):
    """Ручка озвучки сама проверяет ФИО: и в фактах, и в свободном вопросе. До 15.10.2026
    она доверяла вызывающему, и любой вошедший клиент мог отправить фамилии наружу."""
    seen = _sent_to_llm(monkeypatch)
    client, headers = world["client"], world["teacher"]
    facts = f"Должники: {SURNAMES[0]} Батор — 2"
    r = client.post("/vector/voice", json={"facts": facts, "question": "кто должен"}, headers=headers)
    assert r.status_code == 200 and r.json()["text"] == facts, r.text
    r = client.post("/vector/voice", json={"mode": "chat", "question": f"расскажи про {SURNAMES[1]}"},
                    headers=headers)
    assert r.status_code == 200 and r.json()["text"], r.text
    _assert_clean(seen)
    #Без фамилии — озвучка идёт как раньше (иначе проверка выше была бы просто «всё выключено»).
    client.post("/vector/voice", json={"facts": "Средний балл 4.2"}, headers=headers)
    assert "Средний балл 4.2" in seen


def test_two_letter_surnames_are_caught_as_whole_words(world):
    """«Ли», «Ян» — основой не сравнить, раньше их не проверяли вовсе."""
    from app.db import SessionLocal
    from app.routers.web.vector import _names_a_person
    r = world["client"].post("/sync/push", json={"changes": {"users": [{
        "id": "stud:li", "role": "student", "login": "li", "surname": "Ли", "name": "Вэй",
        "password_hash": hash_password("studpass1"), "group_name": "ИС-21"}]}},
        headers=world["admin"])
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        assert _names_a_person("какие оценки у Ли", db)
        assert not _names_a_person("Лиза принесла справку", db), "часть слова — не фамилия"
    finally:
        db.close()
