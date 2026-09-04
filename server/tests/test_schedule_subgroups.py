"""
test_schedule_subgroups.py — ДВЕ ПОДГРУППЫ В ОДНОЙ ПАРЕ (жалоба Влада, 03.09.2026).

Дословно: «если выставить у новой пары или уже существующей тот номер пары, который уже
есть, — новая пара заменяет полностью старую, из-за чего всё ломается и приходится
отменять действие». Плюс: «у преподавателей и студентов показываются разные первые пары
(когда у разных подгрупп одной пары идут пары у разных преподавателей), но в админке
этого нет — сделай такое расписание для всех».

Причина была одна на обе половины жалобы: номер пары входил в ПЕРВИЧНЫЙ КЛЮЧ правки
(`sovr:{группа}|{неделя}|{день}|{номер}`), поэтому в ячейку помещалась ровно одна пара, а
вторая затирала первую молча — вместе с чужой работой.

Что здесь держится (и что покраснеет, если правку откатить):
  • две подгруппы живут в одном слоте и НЕ вытесняют друг друга;
  • «Совместно» (0) по-прежнему вытесняет всё в слоте — иначе человек увидел бы два
    занятия в одно время;
  • правка той же подгруппы по-прежнему ЗАМЕНЯЕТ прежнюю (иначе накопился бы мусор);
  • ключ для «Совместно» остался СТАРОГО формата — иначе синк привёз бы на другой ПК
    каждую существующую правку как новую, рядом со старой.
"""
from app.models import schedule_override_id
from conftest import make_admin

GROUP = "К74/1"


def _ov(client, admin, **kw):
    body = {"group": GROUP, "week": 1, "day": "Пнд", "pair_no": 1, "action": "set", **kw}
    r = client.post("/web/admin/schedule/override", json=body, headers=admin)
    assert r.status_code == 200, r.text
    return r


def _cells(client, admin):
    r = client.get("/web/admin/schedule", params={"group": GROUP}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["overrides"]


def test_two_subgroups_share_one_pair_slot(client):
    """🔥 Главное: вторая пара в том же слоте НЕ стирает первую."""
    admin = make_admin(client)
    _ov(client, admin, subgroup=1, subject="Технология разработки ПО", teacher="Иванов И.И.")
    _ov(client, admin, subgroup=2, subject="Физика", teacher="Петров П.П.")

    cells = _cells(client, admin)
    subjects = {c["subgroup"]: c["subject"] for c in cells if c["pair_no"] == 1}
    assert subjects == {1: "Технология разработки ПО", 2: "Физика"}, cells


def test_editing_the_same_subgroup_still_replaces(client):
    """Обратная сторона: правка ТОЙ ЖЕ подгруппы обязана заменять, а не плодить строки."""
    admin = make_admin(client)
    _ov(client, admin, subgroup=1, subject="Физика")
    _ov(client, admin, subgroup=1, subject="Химия")

    first = [c for c in _cells(client, admin) if c["pair_no"] == 1]
    assert len(first) == 1 and first[0]["subject"] == "Химия", first


def test_joint_pair_displaces_both_subgroups(client):
    """«Совместно» вытесняет половинные пары: два занятия в одно время — это ошибка."""
    admin = make_admin(client)
    _ov(client, admin, subgroup=1, subject="Физика")
    _ov(client, admin, subgroup=2, subject="Химия")
    _ov(client, admin, subgroup=0, subject="Классный час")

    from app.routers.web import _apply_overrides
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        merged = _apply_overrides(db, GROUP, None)
    finally:
        db.close()
    day = merged["weeks"]["1"]["Пнд"]
    assert [x["subject"] for x in day if x["pair_no"] == 1] == ["Классный час"], day


def test_merged_schedule_shows_both_subgroups_in_order(client):
    """Расписание отдаёт ОБЕ пары слота, и порядок устойчив (иначе «расписание скачет»)."""
    admin = make_admin(client)
    _ov(client, admin, subgroup=2, subject="Химия")
    _ov(client, admin, subgroup=1, subject="Физика")

    from app.routers.web import _apply_overrides
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        day = _apply_overrides(db, GROUP, None)["weeks"]["1"]["Пнд"]
    finally:
        db.close()
    first = [x for x in day if x["pair_no"] == 1]
    assert [x["subgroup"] for x in first] == [1, 2], first
    assert [x["subject"] for x in first] == ["Физика", "Химия"]


def test_joint_pair_keeps_the_old_key_format(client):
    """⚠️ Ключ «Совместно» остался БЕЗ хвоста подгруппы.

    Он синкуется между десктопом и сервером. Сменив формат у существующих правок, мы
    привезли бы на каждый ПК их копии рядом со старыми — то есть починка расписания
    сама бы его и сломала.
    """
    assert schedule_override_id(GROUP, 1, "Пнд", 1) == f"sovr:{GROUP}|1|Пнд|1"
    assert schedule_override_id(GROUP, 1, "Пнд", 1, 0) == f"sovr:{GROUP}|1|Пнд|1"
    assert schedule_override_id(GROUP, 1, "Пнд", 1, 2) == f"sovr:{GROUP}|1|Пнд|1|2"


def test_bad_subgroup_is_refused(client):
    """Третьей подгруппы не бывает — молча принимать её нельзя."""
    admin = make_admin(client)
    r = client.post("/web/admin/schedule/override", headers=admin,
                    json={"group": GROUP, "week": 1, "day": "Пнд", "pair_no": 1,
                          "action": "set", "subject": "Физика", "subgroup": 3})
    assert r.status_code == 400, r.text
