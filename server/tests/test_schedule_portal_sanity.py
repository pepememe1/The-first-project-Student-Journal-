"""
test_schedule_portal_sanity.py — 🔒 ПОЛОМКА НА ПОРТАЛЕ НЕ ДОЛЖНА ЛОМАТЬ НАС.

━━ ЗАЧЕМ (04.09.2026, требование Ярослава) ━━
«Расписание починили на портале ВСГУТУ, но надо чтобы потом, если они сломают, у нас
не сломалось.»

Повод настоящий: портал на день выдал группам чужие расписания (у программистов К74/1
стояли пары, связанные с правом). Сам портал починился, но у нас от такого захода
остаются последствия, которых он не заметил бы.

━━ ЧТО ИМЕННО ЛОМАЕТСЯ У НАС ━━
`admin_bind_subjects` ЗАМЕНЯЕТ предметы каждой группы на портальные, а
`_archive_dropped_subjects` при этом:
  • гасит `SubjectHours` выпавших предметов (учебные часы за семестр);
  • ОТКРЕПЛЯЕТ обоих преподавателей (`teacher_id`, `teacher_id_2`).
Один заход с испорченным снимком стирает работу за семестр — и делает это МОЛЧА, отдав
в ответе бодрое «ok: true, bound: 89». Вернуть можно только руками.

━━ ПОЧЕМУ ПОДТВЕРЖДЕНИЕ, А НЕ ЗАПРЕТ ━━
«Предметы сильно изменились» — НЕ признак поломки: в начале семестра набор меняется
почти целиком, и это норма. Признак — массовость: когда так меняется у десятков групп
разом. Запрет остановил бы законный сентябрьский импорт, и админ пошёл бы искать
обходной путь (правку базы руками). Подтверждение оставляет решение человеку, но
лишает его возможности НЕ ЗАМЕТИТЬ.

Тот же приём, что у опасных команд в разделе «Сервер» (§16): не запрещаем — не даём
сделать вслепую.
"""
from app import schedule_web
from app.models import Group, SubjectHours
from schedule import parser as P
from conftest import make_admin


def setup_function(_):
    schedule_web.invalidate_all()


def _snapshot(monkeypatch, groups: dict):
    """Снимок расписания из {имя группы: [предметы]} — через настоящий build_snapshot.

    Собираем НЕ вручную, а тем же разбором, каким работает продукт: снимок, слепленный
    в тесте по своим правилам, проверял бы наши представления о формате, а не формат."""
    rows = "".join(
        f'<tr><td><a href="{i}.htm">{name}</a></td></tr>'
        for i, name in enumerate(groups, start=1))
    index_html = f"<table>{rows}</table>"

    pages = {}
    for i, (name, subjects) in enumerate(groups.items(), start=1):
        cells = "".join(
            f"<tr><td>{day}</td><td>лек.{subjects[k % len(subjects)]} ИВАНОВ И.И. а.100</td>"
            f"<td>_</td></tr>"
            for k, day in enumerate(("Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт")))
        pages[f"{i}.htm"] = (
            "<table><tr><td>Пары</td><td>1-я</td><td>2-я</td></tr>"
            "<tr><td>Время</td><td>09:00-10:35</td><td>10:45-12:20</td></tr>"
            + cells + "</table>")

    def _fetch(url, timeout=20):
        if url.endswith("raspisan.htm"):
            return index_html
        for fname, page in pages.items():
            if url.endswith(fname):
                return page
        return ""

    monkeypatch.setattr(P, "fetch_text", _fetch)
    snap = P.build_snapshot(category="college", fetch=_fetch)
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    return snap


def _seed_group(client, admin, name: str, subjects: list):
    client.post("/web/admin/groups", json={"name": name, "subjects": subjects},
                headers=admin)


# ── Штатный случай: защита не мешает ───────────────────────────────────────────────
def test_normal_import_is_not_blocked(client, monkeypatch):
    """Импорт, который ничего не стирает, проходит без подтверждения.

    Это половина требования: сторож, мешающий обычной работе, будет обойдён, и тогда он
    не защитит и в тот раз, ради которого заведён."""
    admin = make_admin(client)
    _seed_group(client, admin, "К1", ["Математика"])
    _snapshot(monkeypatch, {"К1": ["Математика", "Физика"]})

    r = client.post("/web/admin/groups/bind-subjects", json={}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True
    assert not r.json().get("needs_confirm")


def test_a_couple_of_changed_groups_pass(client, monkeypatch):
    """Одна-две группы со сменившимся набором — норма (перевели на другой план).

    Порог по КОЛИЧЕСТВУ, а не по силе изменения у одной группы: иначе первый же
    законный перевод группы упёрся бы в подтверждение."""
    admin = make_admin(client)
    _seed_group(client, admin, "К1", ["Математика", "Физика"])
    _seed_group(client, admin, "К2", ["Математика", "Физика"])
    _snapshot(monkeypatch, {"К1": ["Право", "Экономика"],
                            "К2": ["Математика", "Физика"]})

    r = client.post("/web/admin/groups/bind-subjects", json={}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()


# ── Порча: массовая подмена ────────────────────────────────────────────────────────
def _mass_swap(client, monkeypatch):
    admin = make_admin(client)
    old = ["Разработка программных модулей", "Дискретная математика"]
    new = ["Гражданское право", "Уголовный процесс"]
    for n in ("К74/1", "К74/2", "К74/3", "К75/1"):
        _seed_group(client, admin, n, old)
    _snapshot(monkeypatch, {n: new for n in ("К74/1", "К74/2", "К74/3", "К75/1")})
    return admin


def test_mass_replacement_needs_confirmation(client, monkeypatch):
    """🔥 ГЛАВНАЯ ПРОВЕРКА: снимок, подменяющий предметы у всех групп разом, не
    применяется молча.

    Обратный ход проверен 04.09.2026: убираю возврат `needs_confirm` — тест краснеет,
    предметы заменяются, часы гаснут."""
    admin = _mass_swap(client, monkeypatch)

    r = client.post("/web/admin/groups/bind-subjects", json={}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("needs_confirm") is True, body
    assert body.get("ok") is False
    assert body["suspicious_count"] >= 3
    # в ответе видно, ЧТО именно теряется — решение принимают по списку, а не по числу
    assert body["suspicious"], body
    lost = body["suspicious"][0]["loses"]
    assert any("программн" in s.lower() for s in lost), lost


def test_nothing_is_written_when_confirmation_is_required(client, monkeypatch):
    """Отказ обязан быть ПОЛНЫМ: ни одна группа не должна успеть измениться.

    Частично применённый импорт хуже отказа — часть групп на новом наборе, часть на
    старом, и понять, где правда, нельзя ни по одному экрану."""
    admin = _mass_swap(client, monkeypatch)
    client.post("/web/admin/groups/bind-subjects", json={}, headers=admin)

    r = client.get("/web/admin/groups", headers=admin)
    assert r.status_code == 200, r.text
    for g in r.json().get("groups", []):
        if g["name"].startswith("К7"):
            subs = " ".join(g.get("subjects") or [])
            assert "право" not in subs.lower(), (
                f"группа {g['name']} всё-таки получила чужие предметы: {subs}")


def test_confirmation_lets_the_admin_through(client, monkeypatch):
    """С явным подтверждением импорт применяется.

    Дверь наружу обязана быть: в начале семестра набор меняется законно и целиком, и
    сторож без обхода превратился бы в неисправность."""
    admin = _mass_swap(client, monkeypatch)

    r = client.post("/web/admin/groups/bind-subjects", json={"confirm": True},
                    headers=admin)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()
    assert r.json().get("bound", 0) >= 3


def test_new_groups_do_not_count_as_suspicious(client, monkeypatch):
    """Группа, которой у нас ещё нет, подозрительной не считается — терять у неё нечего.

    Иначе первый же импорт на чистой базе упёрся бы в подтверждение, и сторож научил бы
    админа жать «подтвердить» не глядя — то есть отменил бы сам себя."""
    admin = make_admin(client)
    _snapshot(monkeypatch, {"К90": ["Право"], "К91": ["Право"],
                            "К92": ["Право"], "К93": ["Право"]})

    r = client.post("/web/admin/groups/bind-subjects", json={}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True, r.json()
