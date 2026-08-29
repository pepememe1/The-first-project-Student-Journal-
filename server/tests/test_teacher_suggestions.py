"""
test_teacher_suggestions.py — «кто ведёт предмет» из расписания портала.

Жалоба 28.08.2026: «изменилось расписание в портале, а предметы, которые преподаёт
препод, не изменились». Причина: `bind-subjects` переносил из расписания только НАЗВАНИЯ
предметов, а связь «кто ведёт» (`SubjectHours.teacher_id`) велась отдельно и руками —
портал знает преподавателя в каждой ячейке, но эта информация не использовалась нигде.

Что здесь держится:
  • подсказки НИЧЕГО не пишут — назначение происходит только явным `apply-teachers`;
  • неоднозначное ФИО остаётся неоднозначным (не «берём первого похожего»);
  • применить можно только существующую строку ТЕКУЩЕГО термина и только реального
    преподавателя — клиентскому списку не доверяем;
  • метку `updated_at` ставит сервер, иначе LWW вернул бы прежнего преподавателя.
"""
from app import schedule_web
from conftest import make_admin


class _Lesson:
    def __init__(self, subject, teacher):
        self.subject = subject
        self.teacher = teacher


class _GroupSched:
    def __init__(self, lessons):
        self._lessons = lessons

    def all_lessons(self):
        for ls in self._lessons:
            yield (1, "Пн", ls)


class _Snap:
    def __init__(self, groups):
        self.groups = groups


def _portal(monkeypatch, groups):
    """Подменяем снимок расписания: сеть в тестах не трогаем."""
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (_Snap(groups), False))


def _teacher(client, admin, login, surname, name, subjects=()):
    """Преподаватель с НАСТОЯЩИМ ФИО.

    `conftest.make_teacher` кладёт всем full_name «Преподаватель» — для сопоставления по
    фамилии и инициалам этого мало, поэтому здесь свой заводитель."""
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"teach:{login}", "role": "teacher", "login": login,
        "password_hash": hash_password("teacherpass1"),
        "full_name": f"{surname} {name}", "surname": surname, "name": name,
        "subjects": list(subjects),
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    return f"teach:{login}"


def _login(client, login):
    r = client.post("/auth/login", json={"login": login, "password": "teacherpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _hours(client, admin, group, subject, teacher_id=""):
    """Строка плана через ту же ручку, которой пользуется админка (пишет ПАЧКОЙ)."""
    r = client.post("/web/admin/group-hours", json={
        "group": group, "hours": {subject: 36}, "teachers": {subject: teacher_id},
    }, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _suggest(client, admin, group=""):
    r = client.get("/web/admin/schedule/teacher-suggestions",
                   params={"group": group} if group else {}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _row(items, subject):
    return next(i for i in items if i["subject"] == subject)


def test_confident_suggestion_is_offered_but_not_applied(client, monkeypatch):
    """ГЛАВНОЕ: подсказка появилась, но в базе по-прежнему пусто — ручка не пишет."""
    admin = make_admin(client)
    _teacher(client, admin, "mikheev", "Михеев", "Борис Владимирович")
    _hours(client, admin, "К16", "История")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("История", "МИХЕЕВ Б.В.")])})

    row = _row(_suggest(client, admin)["items"], "История")
    assert row["state"] == "assign"
    assert row["suggested_teacher_id"] == "teach:mikheev"
    assert row["current_teacher_id"] == ""        # ничего не записано

    #и повторный запрос по-прежнему видит пустое назначение
    assert _row(_suggest(client, admin)["items"], "История")["current_teacher_id"] == ""


def test_apply_writes_the_assignment(client, monkeypatch):
    admin = make_admin(client)
    _teacher(client, admin, "mikheev", "Михеев", "Борис Владимирович")
    _hours(client, admin, "К16", "История")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("История", "МИХЕЕВ Б.В.")])})

    row = _row(_suggest(client, admin)["items"], "История")
    r = client.post("/web/admin/schedule/apply-teachers", json={"entries": [
        {"hours_id": row["hours_id"], "teacher_id": row["suggested_teacher_id"]}]},
        headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 1

    after = _row(_suggest(client, admin)["items"], "История")
    assert after["current_teacher_id"] == "teach:mikheev"
    assert after["state"] == "ok"                 # портал и база согласны — делать нечего


def test_namesakes_stay_ambiguous(client, monkeypatch):
    """🔥 Двое с одной фамилией и одним инициалом — выбирать обязан человек.

    Молчаливый выбор первого по списку и есть тот способ выдать ЧУЖОЙ журнал (доступ к
    оценкам и посещаемости чужой группы), ради которого всё это делается подсказками."""
    admin = make_admin(client)
    _teacher(client, admin, "iv1", "Иванов", "Иван")
    _teacher(client, admin, "iv2", "Иванов", "Игорь")
    _hours(client, admin, "К16", "Физика")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("Физика", "ИВАНОВ И.")])})

    row = _row(_suggest(client, admin)["items"], "Физика")
    assert row["state"] == "ambiguous"
    assert row["suggested_teacher_id"] == ""
    assert len(row["portal"][0]["candidates"]) == 2


def test_two_different_teachers_on_one_subject_is_a_conflict(client, monkeypatch):
    """Лекции ведёт один, практику другой. Наша модель держит ОДНОГО — выбирает человек."""
    admin = make_admin(client)
    _teacher(client, admin, "a", "Михеев", "Борис Владимирович")
    _teacher(client, admin, "b", "Базарова", "Светлана Борисовна")
    _hours(client, admin, "К16", "История")
    _portal(monkeypatch, {"К16": _GroupSched([
        _Lesson("История", "МИХЕЕВ Б.В."),
        _Lesson("История", "БАЗАРОВА С.Б."),
        _Lesson("История", "МИХЕЕВ Б.В."),
    ])})

    row = _row(_suggest(client, admin)["items"], "История")
    assert row["state"] == "conflict"
    assert row["suggested_teacher_id"] == ""
    #Порядок по числу пар: у Михеева их две — он первым, но выбор всё равно за админом.
    assert row["portal"][0]["name"] == "МИХЕЕВ Б.В."
    assert row["portal"][0]["lessons"] == 2


def test_unknown_teacher_is_reported_not_invented(client, monkeypatch):
    admin = make_admin(client)
    _teacher(client, admin, "a", "Михеев", "Борис Владимирович")
    _hours(client, admin, "К16", "Химия")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("Химия", "СЯЧИНОВА Н.В.")])})

    row = _row(_suggest(client, admin)["items"], "Химия")
    assert row["state"] == "unknown"
    assert row["suggested_teacher_id"] == ""


def test_subject_absent_from_schedule_is_marked_no_portal(client, monkeypatch):
    """Предмет в плане есть, а в расписании его никто не ведёт — это не ошибка, а факт."""
    admin = make_admin(client)
    _hours(client, admin, "К16", "Практика")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("История", "МИХЕЕВ Б.В.")])})

    assert _row(_suggest(client, admin)["items"], "Практика")["state"] == "no_portal"


def test_subgroup_tag_does_not_split_the_subject(client, monkeypatch):
    """«Информатика- 1 п/г» на портале и «Информатика» в плане — ОДИН предмет.

    Без нормализации подсказка не нашлась бы, и предмет висел бы как `no_portal` —
    ровно та же болезнь, что уже ловили в импорте предметов."""
    admin = make_admin(client)
    _teacher(client, admin, "a", "Ким", "Сергей Викторович")
    _hours(client, admin, "К16", "Информатика")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("Информатика- 1 п/г", "КИМ С.В.")])})

    row = _row(_suggest(client, admin)["items"], "Информатика")
    assert row["state"] == "assign"
    assert row["suggested_teacher_id"] == "teach:a"


def test_apply_rejects_unknown_teacher_and_foreign_row(client, monkeypatch):
    """Клиентскому списку не доверяем: подсказки он получил от нас, вернуть может что угодно."""
    admin = make_admin(client)
    _teacher(client, admin, "a", "Михеев", "Борис Владимирович")
    _hours(client, admin, "К16", "История")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("История", "МИХЕЕВ Б.В.")])})
    hid = _row(_suggest(client, admin)["items"], "История")["hours_id"]

    r = client.post("/web/admin/schedule/apply-teachers", json={"entries": [
        {"hours_id": hid, "teacher_id": "teach:НЕТ_ТАКОГО"},        # чужой преподаватель
        {"hours_id": "hrs:Чужая|Предмет|2000/2001|1", "teacher_id": "teach:a"},  # чужая строка
    ]}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["applied"], body["skipped"]) == (0, 2)
    assert _row(_suggest(client, admin)["items"], "История")["current_teacher_id"] == ""


def test_apply_can_clear_the_teacher(client, monkeypatch):
    """Пустой teacher_id — законное «снять преподавателя», а не ошибка ввода."""
    admin = make_admin(client)
    _teacher(client, admin, "a", "Михеев", "Борис Владимирович", subjects=["История"])
    _hours(client, admin, "К16", "История", teacher_id="teach:a")
    _portal(monkeypatch, {"К16": _GroupSched([])})
    hid = _row(_suggest(client, admin)["items"], "История")["hours_id"]

    r = client.post("/web/admin/schedule/apply-teachers",
                    json={"entries": [{"hours_id": hid, "teacher_id": ""}]}, headers=admin)
    assert r.json()["applied"] == 1
    assert _row(_suggest(client, admin)["items"], "История")["current_teacher_id"] == ""


def test_only_admin_may_see_and_apply(client, monkeypatch):
    admin = make_admin(client)
    _teacher(client, admin, "a", "Михеев", "Борис Владимирович")
    teacher = _login(client, "a")
    _hours(client, admin, "К16", "История")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("История", "МИХЕЕВ Б.В.")])})

    assert client.get("/web/admin/schedule/teacher-suggestions",
                      headers=teacher).status_code == 403
    assert client.post("/web/admin/schedule/apply-teachers",
                       json={"entries": [{"hours_id": "x", "teacher_id": "y"}]},
                       headers=teacher).status_code == 403


def test_empty_entries_is_a_bad_request(client):
    admin = make_admin(client)
    assert client.post("/web/admin/schedule/apply-teachers",
                       json={"entries": []}, headers=admin).status_code == 400


def test_apply_adds_the_subject_to_the_teacher(client, monkeypatch):
    """Назначение дописывает предмет в список преподавателя.

    Соседняя ручка часов отвечает 400 на назначение предмета, которого нет у препода;
    разойтись с ней нельзя — состояние «ведёт то, чего не ведёт» недостижимо через
    админку. Поэтому правило выполняется тем же действием, а не обходится.

    Обратный ход: убери дописывание — и после `apply-teachers` ручка часов начнёт
    отказывать на той же самой паре, которую сама же и предложила."""
    admin = make_admin(client)
    _teacher(client, admin, "a", "Михеев", "Борис Владимирович")      # без предметов
    _hours(client, admin, "К16", "История")
    _portal(monkeypatch, {"К16": _GroupSched([_Lesson("История", "МИХЕЕВ Б.В.")])})

    hid = _row(_suggest(client, admin)["items"], "История")["hours_id"]
    r = client.post("/web/admin/schedule/apply-teachers",
                    json={"entries": [{"hours_id": hid, "teacher_id": "teach:a"}]},
                    headers=admin)
    assert r.json()["applied"] == 1
    assert r.json()["linked_subjects"] == 1

    #Настоящая проверка: та же пара теперь принимается ОБЫЧНОЙ ручкой часов.
    _hours(client, admin, "К16", "История", teacher_id="teach:a")
    assert _row(_suggest(client, admin)["items"], "История")["current_teacher_id"] == "teach:a"
