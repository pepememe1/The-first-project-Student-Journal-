"""
test_sync_simulator.py — детерминированный симулятор синка (исследование синка W-19, П8).

━━ ЗАЧЕМ ━━
Каждое правило синка проверено по отдельности, а ломается синк на ПЕРЕМЕЖЕНИЯХ: pull
остановился на середине, в это время прошла правка со старой меткой, потом удаление, потом
сменилось назначение преподавателя. Здесь настоящий сервер (тот же `TestClient`) и две
«программы», которые делают ровно то, что делает копия: тянут страницы по курсору,
применяют удаления, пересобираются по `reset`, досылают правки с базой по номеру. События
идут в случайном порядке, но ПО ЗЕРНУ — упавший прогон воспроизводится тем же зерном.

━━ ЧТО ОБЯЗАНО ВЫПОЛНЯТЬСЯ В ЛЮБОМ ПОРЯДКЕ ━━
1. Копия, собранная дельтами, удалениями и сбросами, после затишья РАВНА полному снимку с
   нуля — строка в строку, включая номер изменения (ничего не потеряно и лишнего нет).
2. В копии нет строк чужой области видимости (у преподавателя — только его группы).
3. Правка на свежей базе принимается; на устаревшей и с другим значением — 409, и
   значение на сервере после 409 НЕ меняется.
4. Последняя принятая правка клетки — то, что лежит на сервере.

⚠️ «Программа» здесь — модель протокола, а не `desktop/local_mirror.py`: серверный процесс
и копия программы не уживаются в одном интерпретаторе (у них общий пакет `app`). Код
зеркала проверяется отдельно на той же семантике страниц (`tests/test_mirror_cursor.py`);
симулятор держит ДРУГУЮ сторону договора — что настоящий сервер эту семантику соблюдает.
⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН (`rev_sim.py` захода): выдача без журнала удалений, без сброса
по области видимости и приём правки без сверки базы — каждое красит прогон. Гонку двух
запросов симулятор НЕ ловит (он однопоточный) — её держит
`test_sync_change_seq.py::test_concurrent_write_between_read_and_check_is_caught`.
🔥 Окупился в первый же прогон: полная сверка программы стирала живую строку, если в
одной странице ехали её старое удаление и новая вставка (`local_mirror._seq_full`).
"""
import random

from conftest import make_admin, make_teacher, assign_teacher

SEEDS = range(8)
STEPS = 70
#ИС-33 переходит из рук в руки (смена области видимости), свою группу каждый оставляет
#себе: преподаватель БЕЗ единого назначения по правилу продукта пишет по предмету в любую
#группу (мост `teacher_assignments`), и симулятор проверял бы уже другой режим.
GROUPS = ("ИС-31", "ИС-32", "ИС-33")
STUDENTS = {"ИС-31": ("s31a", "s31b"), "ИС-32": ("s32a", "s32b"), "ИС-33": ("s33a",)}


def _term():
    from app.db import SessionLocal
    from app import webdata as W
    with SessionLocal() as db:
        return W.current_term(W.load_config(db))


def _push(client, h, **entities):
    r = client.post("/sync/push", json={"changes": entities}, headers=h)
    assert r.status_code == 200, r.text


def _world(client):
    from app.security import hash_password
    ty, ts = _term()
    admin = make_admin(client)
    teachers = {"t31": make_teacher(client, admin, "t31", subjects=("Химия",)),
                "t32": make_teacher(client, admin, "t32", subjects=("Химия",))}
    assign_teacher(client, admin, "teach:t31", "ИС-31", "Химия")
    assign_teacher(client, admin, "teach:t32", "ИС-32", "Химия")
    assign_teacher(client, admin, "teach:t31", "ИС-33", "Химия")
    users, lessons = [], []
    for g, logins in STUDENTS.items():
        for login in logins:
            users.append({"id": f"stud:{login}", "role": "student", "login": login,
                          "password_hash": hash_password("x"), "surname": f"Ф{login}",
                          "name": f"И{login}", "group_name": g})
        for n in (1, 2):
            lessons.append({"id": f"L-{g}-{n}", "group_name": g, "subject": "Химия",
                            "type": "Практика", "number": n, "year": ty, "semester": ts})
    _push(client, admin, users=users, lessons=lessons)
    return admin, teachers


class Program:
    """Копия программы в миниатюре: {таблица: {ключ: строка}}, курсор, область, метка."""

    def __init__(self, client, headers, limit):
        self.c, self.h, self.limit = client, headers, limit
        self.rows, self.cursor, self.scope, self.epoch = {}, 0, "", ""
        self.resets = 0

    def _page(self, cursor):
        r = self.c.get("/sync/pull", headers=self.h, params={
            "cursor": cursor, "limit": self.limit, "scope": self.scope, "epoch": self.epoch})
        assert r.status_code == 200, r.text
        return r.json()

    def step(self):
        """Одна страница дельты (или сброс → полная сверка до конца)."""
        if not self.cursor:
            return self.full()
        p = self._page(self.cursor)
        if p.get("reset"):
            self.resets += 1
            return self.full()
        self._apply(p)
        self.cursor = p["cursor"]
        return p["more"]

    def full(self):
        """Полная сверка: с нуля страницами, неувиденное — долой (как `_seq_full`)."""
        cursor, seen, scope, epoch = 0, {}, "", ""
        while True:
            r = self.c.get("/sync/pull", headers=self.h, params={
                "cursor": cursor, "limit": self.limit, "scope": scope, "epoch": epoch})
            assert r.status_code == 200, r.text
            p = r.json()
            if p.get("reset"):
                cursor, seen, scope, epoch = 0, {}, "", ""
                continue
            if cursor == 0:
                scope, epoch = p["scope"], p["epoch"]
            #Сначала удаления, потом строки: строка в таблице новее своего удаления.
            for name, keys in p["removed"].items():
                seen.setdefault(name, set()).difference_update(keys)
            for name, items in p["changes"].items():
                for it in items:
                    seen.setdefault(name, set()).add(_key(it))
            self._apply(p)
            cursor = p["cursor"]
            if not p["more"]:
                break
        for name in list(self.rows):
            if name == "config":
                continue
            for k in list(self.rows[name]):
                if k not in seen.get(name, set()):
                    del self.rows[name][k]
        self.cursor, self.scope, self.epoch = cursor, scope, epoch
        return False

    def _apply(self, p):
        for name, keys in p["removed"].items():
            for k in keys:
                self.rows.get(name, {}).pop(k, None)
        for name, items in p["changes"].items():
            table = self.rows.setdefault(name, {})
            for it in items:
                cur = table.get(_key(it))
                if cur is not None and cur["change_seq"] > it["change_seq"]:
                    continue                  #страница старше увиденного — не откатываем
                table[_key(it)] = it

    def drain(self):
        guard = 0
        while self.step():
            guard += 1
            assert guard < 500, "дельта не сходится к голове"

    def snapshot(self):
        fresh = Program(self.c, self.h, 1000)
        fresh.full()
        return fresh.rows


def _key(it):
    return it.get("id") or it.get("key")


def _strip(rows):
    """Сравнимый вид: вложенные JSON-поля и порядок ключей не должны давать ложных различий."""
    return {n: {k: tuple(sorted((c, repr(v)) for c, v in r.items())) for k, r in t.items()}
            for n, t in rows.items() if n != "config" and t}


def _grade_row(key):
    from app.db import SessionLocal
    from app.models import Grade
    with SessionLocal() as db:
        g = db.get(Grade, key)
        return None if g is None else (g.grade, bool(g.deleted), g.change_seq)


def _no_rate_limit(monkeypatch):
    #Ограничитель частоты (F-22) рассчитан на живую программу — сотни страниц за секунды
    #у симулятора он честно отсёк бы. Здесь проверяется протокол, а не потолок.
    from app.routers import sync as S
    monkeypatch.setattr(S, "PULL_LIMIT", (10 ** 6, 300.0))


def test_random_interleavings_converge_to_a_fresh_snapshot(client, monkeypatch):
    _no_rate_limit(monkeypatch)
    admin, teachers = _world(client)
    from app.db import SessionLocal
    from app.models import Grade, Lesson
    from app import sync_clock
    progs = {name: Program(client, h, limit) for (name, h), limit
             in zip(teachers.items(), (3, 5), strict=True)}
    accepted = {}          #ключ клетки → (номер, значение) последней принятой правки
    owner = {"ИС-31": "t31", "ИС-32": "t32", "ИС-33": "t31"}      #кто сейчас ведёт группу
    buried = set()                                #занятия под надгробием
    stats = {"ok": 0, "conflict": 0, "reset": 0, "denied": 0}
    for seed in SEEDS:
        rnd = random.Random(seed)
        for _ in range(STEPS):
            who = rnd.choice(sorted(progs))
            prog = progs[who]
            mine = sorted(g for g, t in owner.items() if t == who)
            op = rnd.random()
            if op < 0.40:
                #Правка клетки с базой из своей копии (как очередь программы). Группа —
                #случайная из ВСЕХ: чужая обязана получить отказ по правам.
                g = rnd.choice(GROUPS)
                login = rnd.choice(STUDENTS[g])
                lesson = f"L-{g}-{rnd.choice((1, 2))}"
                key = f"stud:{login}|{lesson}"
                have = prog.rows.get("grades", {}).get(key)
                base = have["change_seq"] if have else 0
                value = rnd.choice(("2", "3", "4", "5", ""))
                before = _grade_row(key)
                r = client.post("/web/teacher/grade", headers=teachers[who], json={
                    "lesson_id": lesson, "surname": f"Ф{login}", "name": f"И{login}",
                    "student_id": f"stud:{login}", "grade": value, "base_seq": base})
                if g not in mine or lesson in buried:
                    #Чужая группа — отказ по правам, удалённое занятие — 404. Ничего не
                    #меняется ни в том, ни в другом случае.
                    assert r.status_code in (403, 404), ("правка прошла мимо прав", r.text)
                    stats["denied"] += 1
                    assert _grade_row(key) == before
                elif r.status_code == 200:
                    stats["ok"] += 1
                    body = r.json()
                    accepted[key] = (body["change_seq"], value)
                    #Правка на свежей базе обязана проходить — и проходила именно она.
                    assert before is None or before[2] == base or (
                        before[0] == value and before[1] == (value == "")), (seed, key)
                elif r.status_code == 409:
                    stats["conflict"] += 1
                    assert _grade_row(key) == before, "после 409 значение на сервере изменилось"
                    assert before is not None and before[2] != base, "отказ на свежей базе"
                else:
                    raise AssertionError(r.text)
            elif op < 0.55:
                #Правка «с сайта» без базы и со СТАРОЙ меткой времени (W-02 в чистом виде).
                g = rnd.choice(GROUPS)
                login = rnd.choice(STUDENTS[g])
                with SessionLocal() as db:
                    key = f"stud:{login}|L-{g}-1"
                    row = db.get(Grade, key) or Grade(id=key, student_id=f"stud:{login}",
                                                     student_f=f"Ф{login}", student_n=f"И{login}",
                                                     lesson_id=f"L-{g}-1")
                    row.grade = rnd.choice(("3", "4"))
                    row.deleted = False
                    row.updated_at = "2020-01-01T00:00:00+00:00"
                    db.merge(row)
                    db.commit()
                    accepted[key] = (db.get(Grade, key).change_seq, row.grade)
            elif op < 0.65:
                #Жёсткое удаление строки (уборка надгробий, чистка дублей).
                with SessionLocal() as db:
                    rows = db.query(Grade).all()
                    if rows:
                        victim = rnd.choice(rows)
                        accepted.pop(victim.id, None)
                        db.delete(victim)
                        db.commit()
            elif op < 0.70:
                #Надгробие занятия и его воскрешение — строка меняется, а не пропадает.
                g = rnd.choice(GROUPS)
                lid = f"L-{g}-2"
                with SessionLocal() as db:
                    les = db.get(Lesson, lid)
                    les.deleted = not les.deleted
                    db.commit()
                buried.symmetric_difference_update({lid})
            elif op < 0.76:
                #Смена области видимости: чужую группу отдают этому преподавателю, а
                #отданную возвращают прежнему. Между такими шагами идут pull — копии
                #обязаны пересобраться и выбросить то, что им больше не положено (W-05).
                new_owner = "t32" if owner["ИС-33"] == "t31" else "t31"
                assign_teacher(client, admin, f"teach:{new_owner}", "ИС-33", "Химия")
                owner["ИС-33"] = new_owner
            else:
                #Частичный pull: одна страница, копия остаётся посередине потока.
                prog.step()
        #━━ ЗАТИШЬЕ: все программы дотягивают до головы ━━
        for name, prog in progs.items():
            prog.drain()
            fresh = prog.snapshot()
            assert _strip(prog.rows) == _strip(fresh), \
                f"зерно {seed}: копия {name} разошлась с полным снимком"
            #Области видимости — ровно те группы, что человек ведёт СЕЙЧАС.
            groups = {g for g, t in owner.items() if t == name}
            assert {l["group_name"] for l in prog.rows.get("lessons", {}).values()} <= groups, \
                f"зерно {seed}: в копии {name} занятия чужой группы"
        with SessionLocal() as db:
            head = sync_clock.read(db)["seq"]
            for key, (seq, value) in accepted.items():
                g = db.get(Grade, key)
                if g is None:
                    continue
                if g.change_seq == seq:
                    assert (g.grade if not g.deleted else "") == value, (seed, key)
        assert all(p.cursor <= head for p in progs.values())
    for prog in progs.values():
        stats["reset"] += prog.resets
    #Прогон обязан реально пройти по всем веткам, иначе «зелено» ничего не значит.
    assert stats["ok"] > 20 and stats["conflict"] > 0 and stats["reset"] > 0, stats


def test_scope_change_removes_foreign_rows_from_the_copy(client, monkeypatch):
    """Снятое назначение: после затишья в копии нет ни одной строки снятой группы."""
    _no_rate_limit(monkeypatch)
    admin, teachers = _world(client)
    prog = Program(client, teachers["t31"], 4)
    prog.drain()
    assert any(l["group_name"] == "ИС-33" for l in prog.rows["lessons"].values())
    #ИС-33 отдали второму преподавателю — у первого назначение снято.
    assign_teacher(client, admin, "teach:t32", "ИС-33", "Химия")
    prog.drain()
    assert prog.resets >= 1, "смена области видимости не вызвала сброс"
    assert not [l for l in prog.rows["lessons"].values() if l["group_name"] == "ИС-33"], \
        "в копии остались занятия снятой группы (W-05)"
    assert not [u for u in prog.rows["users"].values()
                if u.get("group_name") == "ИС-33" and u.get("role") == "student"]
