"""
test_group_category.py — Group.category (schedule/parser.py::CATEGORIES) — создание/
правка группы с категорией, эндпоинт импорта каталожной записи по категории,
списочный эндпоинт отдаёт category. Сеть (schedule_web) замокана.
"""
from app import schedule_web
from schedule import parser as P
from conftest import make_admin, make_teacher


def setup_function(_):
    schedule_web.invalidate_all()


# ── создание/правка группы с категорией ──────────────────────────────────────

def test_create_group_defaults_to_college(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups", json={"name": "ИС-21", "subjects": []}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "college"

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "ИС-21")
    assert grp["category"] == "college"


def test_create_group_with_known_category(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups",
                    json={"name": "Б165", "subjects": [], "category": "bakalavriat"},
                    headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "bakalavriat"


def test_create_group_with_unknown_category_falls_back_to_college(client):
    """Неизвестный/мусорный ключ категории — не 400, тихий фолбэк на «college»
    (тот же принцип, что «пусто → college»: не ломаем создание группы из-за
    опечатки в необязательном поле)."""
    admin = make_admin(client)
    r = client.post("/web/admin/groups",
                    json={"name": "ИС-22", "subjects": [], "category": "not-a-real-category"},
                    headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "college"


def test_update_group_category(client):
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "ИС-23", "subjects": []}, headers=admin)
    r = client.put("/web/admin/groups/ИС-23", json={"category": "zo1"}, headers=admin)
    assert r.status_code == 200, r.text

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "ИС-23")
    assert grp["category"] == "zo1"


# ── импорт группы-каталожной записи по категории ─────────────────────────────

def test_import_schedule_category_creates_catalog_only_group(client, monkeypatch):
    """Портал отдаёт только СПИСОК групп (не расписание конкретной) — предметы взять
    неоткуда, группа заводится пустой. Отдельный тест ниже проверяет случай, когда
    расписание группы РЕАЛЬНО доступно."""
    admin = make_admin(client)
    monkeypatch.setattr(P, "fetch_text",
                        lambda url, timeout=20: '<table><tr><td><a href="1.htm">Б165</a></td><td><a href="2.htm">Б175</a></td></tr></table>')

    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "name": "Б165", "category": "bakalavriat"}

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "Б165")
    assert grp["category"] == "bakalavriat"
    assert grp["subjects"] == []          # нет данных о занятиях — нечего подставить


def test_import_schedule_category_fills_subjects_from_schedule(client, monkeypatch):
    """Предметы группа получает ИЗ ЕЁ ЖЕ расписания (то, что уже разобрано парсером) —
    второй сущности «учебный план» для этих категорий нет и не будет."""
    admin = make_admin(client)
    index_html = '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>'
    group_html = (
        "<table>"
        "<tr><td>Пары</td><td>1-я</td><td>2-я</td></tr>"
        "<tr><td>Время</td><td>09:00-10:35</td><td>10:45-12:20</td></tr>"
        "<tr><td>Пнд</td><td>лек.Физика ИВАНОВ И.И. а.100</td><td>пр.Химия ПЕТРОВА П.П. а.101</td></tr>"
        "<tr><td>Втр</td><td>_</td><td>_</td></tr>"
        "<tr><td>Срд</td><td>_</td><td>_</td></tr>"
        "<tr><td>Чтв</td><td>_</td><td>_</td></tr>"
        "<tr><td>Птн</td><td>_</td><td>_</td></tr>"
        "<tr><td>Сбт</td><td>_</td><td>_</td></tr>"
        "</table>"
    )

    def _fetch(url, timeout=20):
        return index_html if url.endswith("raspisan.htm") else group_html
    monkeypatch.setattr(P, "fetch_text", _fetch)

    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r.status_code == 200, r.text

    groups = client.get("/web/admin/groups", headers=admin).json()["groups"]
    grp = next(g for g in groups if g["name"] == "Б165")
    assert grp["subjects"] == ["Физика", "Химия"]


def test_import_schedule_category_rejects_name_not_on_portal(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(P, "fetch_text", lambda url, timeout=20: '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>')

    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Выдуманная-группа"},
                    headers=admin)
    assert r.status_code == 422, r.text


def test_import_schedule_category_rejects_unknown_category(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "not-a-real-category", "group_name": "Б165"},
                    headers=admin)
    assert r.status_code == 400


def test_import_schedule_category_conflicts_on_existing_group(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(P, "fetch_text", lambda url, timeout=20: '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>')
    r1 = client.post("/web/admin/groups/import-schedule-category",
                     json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r1.status_code == 200, r1.text
    r2 = client.post("/web/admin/groups/import-schedule-category",
                     json={"category": "bakalavriat", "group_name": "Б165"}, headers=admin)
    assert r2.status_code == 409


def test_import_schedule_category_requires_admin(client, monkeypatch):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    monkeypatch.setattr(P, "fetch_text", lambda url, timeout=20: '<table><tr><td><a href="1.htm">Б165</a></td></tr></table>')
    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat", "group_name": "Б165"}, headers=teacher)
    assert r.status_code == 403


def test_import_schedule_category_missing_fields_is_400(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-schedule-category",
                    json={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 400


# ── «Все» — массовый импорт ВСЕХ групп категории ──────────────────────────────

def _two_group_snapshot(monkeypatch):
    """Реальный Snapshot двух групп категории (через настоящий build_snapshot +
    подменённый fetch_text) — не собираем dataclass'ы руками, ровно тот же приём,
    что уже применён для одиночного импорта выше в этом файле."""
    index_html = '<table><tr><td><a href="1.htm">Б165</a></td><td><a href="2.htm">Б175</a></td></tr></table>'
    pages = {
        "1.htm": (
            "<table>"
            "<tr><td>Пары</td><td>1-я</td></tr>"
            "<tr><td>Время</td><td>09:00-10:35</td></tr>"
            "<tr><td>Пнд</td><td>лек.Физика ИВАНОВ И.И. а.100</td></tr>"
            "<tr><td>Втр</td><td>_</td></tr><tr><td>Срд</td><td>_</td></tr>"
            "<tr><td>Чтв</td><td>_</td></tr><tr><td>Птн</td><td>_</td></tr>"
            "<tr><td>Сбт</td><td>_</td></tr></table>"),
        "2.htm": (
            "<table>"
            "<tr><td>Пары</td><td>1-я</td></tr>"
            "<tr><td>Время</td><td>09:00-10:35</td></tr>"
            "<tr><td>Пнд</td><td>лек.Химия ПЕТРОВА П.П. а.101</td></tr>"
            "<tr><td>Втр</td><td>_</td></tr><tr><td>Срд</td><td>_</td></tr>"
            "<tr><td>Чтв</td><td>_</td></tr><tr><td>Птн</td><td>_</td></tr>"
            "<tr><td>Сбт</td><td>_</td></tr></table>"),
    }

    def _fetch(url, timeout=20):
        if url.endswith("raspisan.htm"):
            return index_html
        for href, html in pages.items():
            if url.endswith(href):
                return html
        return ""
    monkeypatch.setattr(P, "fetch_text", _fetch)
    #⚠️ build_snapshot(fetch=fetch_text) захватывает fetch_text ЗНАЧЕНИЕМ параметра по
    #умолчанию В МОМЕНТ ОПРЕДЕЛЕНИЯ функции — monkeypatch на P.fetch_text его НЕ меняет
    #(это не атрибут модуля, читаемый заново на каждый вызов). Без явного fetch=_fetch
    #здесь ушёл бы настоящий запрос на портал и попытка обойти все ~200 реальных групп
    #категории — поймано по тесту, который реально повис на живой сети.
    return P.build_snapshot(category="bakalavriat", fetch=_fetch)


def test_import_schedule_category_all_creates_groups_with_subjects(client, monkeypatch):
    admin = make_admin(client)
    snap = _two_group_snapshot(monkeypatch)
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    r = client.post("/web/admin/groups/import-schedule-category-all",
                    json={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ok": True, "building": False, "imported": 2, "updated": 0,
                    "skipped": 0, "total": 2}

    groups = {g["name"]: g for g in client.get("/web/admin/groups", headers=admin).json()["groups"]}
    assert groups["Б165"]["category"] == "bakalavriat"
    assert groups["Б165"]["subjects"] == ["Физика"]
    assert groups["Б175"]["subjects"] == ["Химия"]


def test_import_schedule_category_all_updates_already_imported(client, monkeypatch):
    """Уже заведённая группа не дублируется и не 409-ит — её предметы ОБНОВЛЯЮТСЯ по
    расписанию и считаются в `updated` (раньше такая группа молча пропускалась, и
    «Все» никогда не догоняла портал; парсинг обязан быть одинаковым у всех кнопок).

    Второй прогон подряд — уже no-op: список совпал, `updated` снова 0. Без этой
    половины теста «обновляем всегда» было бы неотличимо от «обновляем, когда надо»,
    а каждый холостой прогон двигал бы `updated_at` и гнал бы группу в синк заново."""
    admin = make_admin(client)
    snap = _two_group_snapshot(monkeypatch)
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    client.post("/web/admin/groups", json={"name": "Б165", "category": "bakalavriat"},
               headers=admin)

    r = client.post("/web/admin/groups/import-schedule-category-all",
                    json={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1 and body["updated"] == 1 and body["total"] == 2
    assert body["skipped"] == 0, "нетронутых групп больше не бывает"

    groups = [g for g in client.get("/web/admin/groups", headers=admin).json()["groups"]
              if g["name"] == "Б165"]
    assert len(groups) == 1, f"группа не должна задвоиться: {groups}"
    assert groups[0]["subjects"] == ["Физика"]

    again = client.post("/web/admin/groups/import-schedule-category-all",
                        json={"category": "bakalavriat"}, headers=admin).json()
    assert again["imported"] == 0 and again["updated"] == 0, "повтор без изменений — no-op"


def test_import_schedule_category_all_backfills_subjects_of_empty_existing_group(client, monkeypatch):
    """Группа могла быть заведена ДО того, как импорт стал подставлять предметы (или
    портал был недоступен в момент её импорта) — «Все» доливает предметы в такую
    ПУСТУЮ запись бесплатно, раз расписание всё равно только что разобрано."""
    admin = make_admin(client)
    snap = _two_group_snapshot(monkeypatch)
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    client.post("/web/admin/groups", json={"name": "Б165", "category": "bakalavriat"},
               headers=admin)   # subjects=[] по умолчанию

    client.post("/web/admin/groups/import-schedule-category-all",
               json={"category": "bakalavriat"}, headers=admin)

    groups = {g["name"]: g for g in client.get("/web/admin/groups", headers=admin).json()["groups"]}
    assert groups["Б165"]["subjects"] == ["Физика"]


def test_import_schedule_category_all_replaces_subjects_and_archives_the_dropped_one(client,
                                                                                    monkeypatch):
    """НЕПУСТОЙ список тоже ЗАМЕНЯЕТСЯ данными расписания — ровно как в одиночном
    импорте, и это главное в правке: раньше «Все» такую группу не трогала никогда.

    Выпавший предмет обязан уйти в АРХИВ, а не остаться висеть: его строка часов
    гасится (`deleted`), и вместе с ней открепляются ОБА преподавателя — иначе
    предмет, вернувшийся в план через полгода, оживал бы с назначениями, которых
    никто не делал, а его ЗЕТ до тех пор утекал бы в знаменатель зачёта.

    Проверяем и через API (активный редактор часов предмета больше не показывает),
    и прямо в строке БД: сам факт исчезновения из выдачи даёт и простое удаление
    строки, а нам нужно именно гашение с обнулёнными слотами преподавателей."""
    admin = make_admin(client)
    snap = _two_group_snapshot(monkeypatch)
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))

    client.post("/web/admin/groups",
               json={"name": "Б165", "category": "bakalavriat", "subjects": ["Своё"]},
               headers=admin)
    #Раздельное обучение — чтобы занять ОБА слота преподавателя: teacher_id_2 раньше
    #переживал уход предмета из плана, и его открепление проверять надо отдельно.
    r = client.post("/web/curator/subject-split",
                    json={"group": "Б165", "subject": "Своё", "split": True}, headers=admin)
    assert r.status_code == 200, r.text
    make_teacher(client, admin, login="t1", password="pass1234", subjects=["Своё"])
    make_teacher(client, admin, login="t2", password="pass1234", subjects=["Своё"])
    r = client.post("/web/admin/group-hours",
                    json={"group": "Б165", "hours": {"Своё": 36},
                          "teachers": {"Своё": "teach:t1"}, "teachers2": {"Своё": "teach:t2"}},
                    headers=admin)
    assert r.status_code == 200, r.text
    before = next(s for s in client.get("/web/admin/group-hours?group=Б165", headers=admin)
                  .json()["subjects"] if s["subject"] == "Своё")
    assert before["teacher_id"] == "teach:t1", before

    body = client.post("/web/admin/groups/import-schedule-category-all",
                       json={"category": "bakalavriat"}, headers=admin).json()
    assert body["updated"] == 1, body

    groups = {g["name"]: g for g in client.get("/web/admin/groups", headers=admin).json()["groups"]}
    assert groups["Б165"]["subjects"] == ["Физика"], "предметы обязаны прийти из расписания"

    after = client.get("/web/admin/group-hours?group=Б165", headers=admin).json()["subjects"]
    assert not any(s["subject"] == "Своё" for s in after), after

    from app.db import SessionLocal
    from app.models import SubjectHours
    db = SessionLocal()
    try:
        row = (db.query(SubjectHours)
               .filter(SubjectHours.group_name == "Б165", SubjectHours.subject == "Своё")
               .first())
        assert row is not None, "строка часов гасится, а не удаляется — история не стирается"
        assert row.deleted is True, "выпавший предмет обязан уйти в архив"
        assert row.teacher_id == "" and row.teacher_id_2 == "", \
            f"оба преподавателя обязаны открепиться: {row.teacher_id!r}/{row.teacher_id_2!r}"
        assert row.hours_total == 36, "часы остаются в архивной строке — это архив, не удаление"
    finally:
        db.close()


def test_import_schedule_category_all_reports_building(client, monkeypatch):
    """Снимок ещё не собран (первый запрос категории) — {ok: false, building: true},
    а не 200 с пустым результатом, который выглядел бы как «в категории нет групп»."""
    admin = make_admin(client)
    from app import schedule_web
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (None, True))

    r = client.post("/web/admin/groups/import-schedule-category-all",
                    json={"category": "bakalavriat"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": False, "building": True, "imported": 0, "skipped": 0, "total": 0}


def test_import_schedule_category_all_rejects_college(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-schedule-category-all",
                    json={"category": "college"}, headers=admin)
    assert r.status_code == 400


def test_import_schedule_category_all_rejects_unknown_category(client):
    admin = make_admin(client)
    r = client.post("/web/admin/groups/import-schedule-category-all",
                    json={"category": "not-a-real-category"}, headers=admin)
    assert r.status_code == 400


def test_import_schedule_category_all_requires_admin(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    r = client.post("/web/admin/groups/import-schedule-category-all",
                    json={"category": "bakalavriat"}, headers=teacher)
    assert r.status_code == 403
