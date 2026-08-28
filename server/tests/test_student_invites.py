"""
test_student_invites.py — приглашение студентов ссылкой: куратор выдаёт, студент входит сам.

Просьба Ярослава: «фича для приглашения студентов». До этого путей было ровно два, и оба
плохие для сентября — админ заводит тридцать человек руками, либо каждый студент подаёт
заявку с экрана входа и ждёт, пока её одобрят по одной.

🔑 ПРИГЛАШЕНИЕ — ЭТО И ЕСТЬ ОДОБРЕНИЕ. Отсюда всё остальное: аккаунт создаётся сразу, а у
ссылки обязаны быть ТРИ ограничителя, и ни один не лишний — срок (вечная ссылка в чате
курса переживёт выпуск и смену куратора), число мест (утёкшая ссылка не должна заводить
сто аккаунтов) и отзыв (единственный способ закрыть утёкшую ссылку немедленно). Правило
«жива ли ссылка» живёт ОДНИМ местом в `reg_utils.invite_blocked_reason`: две копии
разошлись бы молча и в худшую сторону — зелёная в списке куратора, отказ студенту.

⚠️ Обратный ход проверен откатом: если `register_by_invite` начнёт брать группу из тела
запроса вместо приглашения, краснеет `test_group_comes_from_the_invite_not_the_form`;
если убрать проверку `invite_blocked_reason` в `register_by_invite` — краснеют ТРИ
теста (отзыв, места, срок). Оба отката проверены прогоном, а не на глаз.
"""
import pytest

from conftest import make_admin, make_teacher

GROUP = "К-24"
OTHER = "К-25"


def _group(client, admin, name):
    r = client.post("/web/admin/groups", json={"name": name}, headers=admin)
    assert r.status_code in (200, 409), r.text


def _curator(client, admin, login="curator1", groups=(GROUP,)):
    """Преподаватель с кураторством: куратора назначают списком curated_groups."""
    teacher = make_teacher(client, admin, login=login)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"teach:{login}", "role": "teacher", "login": login,
        "curated_groups": list(groups),
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    return f"teach:{login}", teacher


@pytest.fixture()
def cast(client):
    admin = make_admin(client)
    _group(client, admin, GROUP)
    _group(client, admin, OTHER)
    cur_id, curator = _curator(client, admin)
    plain = make_teacher(client, admin, login="plainteacher")
    return {"admin": admin, "curator": curator, "curator_id": cur_id, "plain": plain}


def _make_invite(client, headers, group=GROUP, **extra):
    body = {"group": group}
    body.update(extra)
    return client.post("/web/admin/invites", json=body, headers=headers)


def _register(client, token, email="new@yandex.ru", full_name="Новиков Пётр Ильич"):
    return client.post("/auth/register-invite", json={
        "token": token, "full_name": full_name, "email": email, "phone": "89140000000",
    })


# ── кто вправе выдать ───────────────────────────────────────────────────────────────

def test_admin_issues_an_invite_for_any_group(client, cast):
    r = _make_invite(client, cast["admin"], OTHER)
    assert r.status_code == 200, r.text
    inv = r.json()["invite"]
    assert inv["group"] == OTHER and len(inv["token"]) > 20


def test_curator_issues_an_invite_for_his_own_group(client, cast):
    r = _make_invite(client, cast["curator"], GROUP)
    assert r.status_code == 200, r.text


def test_curator_cannot_invite_into_a_foreign_group(client, cast):
    """Иначе любой куратор заводил бы студентов в чужую группу — это чужие ПДн и чужой журнал."""
    assert _make_invite(client, cast["curator"], OTHER).status_code == 403


def test_a_teacher_without_curatorship_cannot_invite(client, cast):
    assert _make_invite(client, cast["plain"], GROUP).status_code == 403


def test_invite_for_a_missing_group_is_refused(client, cast):
    """Ссылка в несуществующую группу завела бы студента в никуда — и нашлось бы это
    только когда он не увидит журнала."""
    assert _make_invite(client, cast["admin"], "К-999").status_code == 404


# ── регистрация по ссылке ───────────────────────────────────────────────────────────

def test_registration_by_invite_creates_the_account_at_once(client, cast):
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    r = _register(client, token)
    assert r.status_code == 200, r.text
    assert r.json()["login"] == "new@yandex.ru" and r.json()["group"] == GROUP
    # Человек может войти сразу — второго круга согласований нет, в этом весь смысл.
    students = client.get(f"/web/admin/students?group={GROUP}", headers=cast["admin"])
    assert students.status_code == 200, students.text
    names = [f'{s.get("surname", "")} {s.get("name", "")}'.strip()
             for s in students.json().get("students", [])]
    assert any("Новиков" in n for n in names), names
    # ФИО разбирается ТОЙ ЖЕ функцией, что у одобрения заявки: фамилия отдельно,
    # «Имя Отчество» в поле name (исторический ключ ростера — его не меняли).
    assert any(n == "Новиков Пётр Ильич" for n in names), names


def test_group_comes_from_the_invite_not_the_form(client, cast):
    """Иначе ссылка в К-24 заводила бы студента в любую другую группу, и ограничение
    «куратор приглашает только к себе» не значило бы ничего."""
    token = _make_invite(client, cast["curator"], GROUP).json()["invite"]["token"]
    r = client.post("/auth/register-invite", json={
        "token": token, "full_name": "Новиков Пётр", "email": "new@yandex.ru",
        "phone": "89140000000", "group": OTHER,          # ← подсунутая группа
    })
    assert r.status_code == 200, r.text
    assert r.json()["group"] == GROUP


def test_public_check_tells_the_group_before_the_form(client, cast):
    """Экран регистрации обязан показать, КУДА человек вступает: «просто заполните форму»
    без названия группы — это подпись под неизвестным."""
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    r = client.get(f"/auth/invite/{token}")
    assert r.status_code == 200, r.text
    assert r.json()["group"] == GROUP


def test_bad_data_is_refused(client, cast):
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    assert _register(client, token, email="who@gmail.com").status_code == 400   # чужой домен
    assert _register(client, token, full_name="Пётр").status_code == 400        # без фамилии


def test_duplicate_email_does_not_burn_a_seat(client, cast):
    """⚠️ Место расходуется ТОЛЬКО после успешного создания. Иначе десять опечаток в почте
    съели бы десять мест группы, и последние студенты остались бы за дверью."""
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    assert _register(client, token).status_code == 200
    assert _register(client, token).status_code == 409          # та же почта
    lst = client.get("/web/admin/invites", headers=cast["admin"]).json()["invites"]
    assert lst[0]["uses"] == 1, lst


# ── три ограничителя ────────────────────────────────────────────────────────────────

def test_revoked_invite_stops_working(client, cast):
    """Единственный способ закрыть УЖЕ УТЁКШУЮ ссылку, не дожидаясь срока."""
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    assert client.post(f"/web/admin/invites/{token}/revoke",
                       headers=cast["curator"]).status_code == 200
    r = _register(client, token)
    assert r.status_code == 404
    assert "отозвано" in r.json()["detail"].lower()
    # И публичная проверка обязана говорить то же самое — правило одно на обе стороны.
    assert client.get(f"/auth/invite/{token}").status_code == 404


def test_seats_run_out(client, cast):
    token = _make_invite(client, cast["curator"], max_uses=1).json()["invite"]["token"]
    assert _register(client, token, email="a@yandex.ru").status_code == 200
    r = _register(client, token, email="b@yandex.ru", full_name="Борисов Борис")
    assert r.status_code == 404
    assert "максимальное" in r.json()["detail"].lower()


def test_expired_invite_stops_working(client, cast):
    """Срок проверяется тем же общим правилом; двигаем метку в прошлое прямо в базе."""
    from app.db import SessionLocal
    from app.models import StudentInvite
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    db = SessionLocal()
    try:
        inv = db.get(StudentInvite, token)
        inv.expires_at = "2000-01-01T00:00:00Z"
        db.commit()
    finally:
        db.close()
    r = _register(client, token)
    assert r.status_code == 404
    assert "срок" in r.json()["detail"].lower()


def test_unknown_token_is_refused(client, cast):
    assert _register(client, "нетакого").status_code == 404
    assert client.get("/auth/invite/нетакого").status_code == 404


# ── список и границы видимости ──────────────────────────────────────────────────────

def test_curator_sees_invites_of_his_group_even_if_admin_issued_them(client, cast):
    """⚠️ Не только выданные ЛИЧНО им: группу ведут вдвоём с админом, и ссылка, о которой
    куратор не знает, — это открытая дверь, которую он не может закрыть."""
    _make_invite(client, cast["admin"], GROUP)
    rows = client.get("/web/admin/invites", headers=cast["curator"]).json()["invites"]
    assert len(rows) == 1 and rows[0]["group"] == GROUP


def test_curator_does_not_see_foreign_invites(client, cast):
    _make_invite(client, cast["admin"], OTHER)
    rows = client.get("/web/admin/invites", headers=cast["curator"]).json()["invites"]
    assert rows == []


def test_the_list_says_whether_the_link_still_works(client, cast):
    """Куратор должен видеть состояние ссылки, а не только её текст: иначе он раздаст
    мёртвую и узнает об этом от студентов."""
    token = _make_invite(client, cast["curator"]).json()["invite"]["token"]
    client.post(f"/web/admin/invites/{token}/revoke", headers=cast["curator"])
    row = client.get("/web/admin/invites", headers=cast["curator"]).json()["invites"][0]
    assert row["alive"] is False and row["reason"]
