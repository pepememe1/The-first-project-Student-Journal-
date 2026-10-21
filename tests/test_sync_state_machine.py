"""
test_sync_state_machine.py — синхронизация программы как конечный автомат (21.10.2026).

━━ ЗАЧЕМ ━━
Остальные тесты синка проверяют сценарии, которые мы ПРИДУМАЛИ: «правка-сирота», «цепочка
своих правок», «сброс области». Опасные ошибки синхронизации живут в сочетаниях, которые
не придумал никто: обрыв на третьей правке из пяти, потерянный ответ, а следом чужая
правка той же строки и полная сверка. Здесь генератор строит случайные ПОСЛЕДОВАТЕЛЬНОСТИ
действий и проверяет свойства не только в конце, но и ПОСЛЕ КАЖДОГО ПЕРЕХОДА: система
может прийти к верному итогу, по дороге нарушив безопасность (отправив правку чужим
токеном или показав откат оценки).
Это приём проверки на моделях (model-based / stateful property testing, как
`RuleBasedStateMachine` в Hypothesis), сделанный на стандартной библиотеке: случайность
— от номера seed, поэтому любой красный прогон воспроизводится тем же номером.

━━ АВТОМАТ ━━
Состояние: строки боя (`Prod`), копия программы, очередь досылки, кто вошёл. Переходы:
  правка в программе   — копия меняется сразу, правка встаёт в очередь (как обработчик);
  сбой процесса        — правка встала в очередь, а ответа обработчика нет («сирота»);
  чужая правка на бою  — другой преподаватель меняет или удаляет ту же строку;
  сброс области        — бой сменил область видимости, копия обязана пройти заново;
  досылка              — сеть: норма; обрыв ДО записи; ответ потерян ПОСЛЕ записи;
  зеркало              — проход по курсору (и полная сверка, если её попросили);
  решение человека     — по конфликту: «оставить моё» или «оставить серверное»;
  смена учётной записи — за компьютер сел другой человек, фоновая досылка ещё живёт;
  снимок и восстановление — бой откатывается к снимку; поколение меняется, номера
                         перескакивают вперёд (как делает `sync_clock.check_restore`).
Бой ведёт себя по контракту `write.py` + `_ensure_base_version`: конфликт — только если
строку изменили после номера, на котором стоял автор, И значение отличается; повтор того
же значения — НЕ запись (идемпотентность, правка 21.10.2026).

━━ ИНВАРИАНТЫ ━━
1. Идемпотентность: повтор правки после потерянного ответа не спорит сам с собой и не
   создаёт второй версии строки на бою.
2. Ни одна правка не теряется молча: в конце каждая либо принята боем, либо человек сам
   сказал «оставить серверное»; пока не решено — на экране остаётся его значение.
3. Курсор честный: после прохода зеркала всё, что бой закоммитил до курсора, в копии
   есть (или защищено правкой из очереди); удалённое до курсора — удалено.
4. Сбой процесса между очередью и ответом не теряет правку («сирота» уходит на бой).
5. Изоляция людей: правка не уходит чужим токеном; новый человек не видит чужой очереди.
6. Восстановление боя из копии: копия программы сходится с восстановленным боем, правки
   из очереди не теряются молча, а то, что бой потерял, человек видит в карантине и сам
   решает — вернуть или убрать (сценарии разбора Ярослава 21.10.2026).
"""
import copy as _copy
import base64
import json
import random

import pytest

from desktop import desk_outbox, local_mirror
from test_mirror_cursor import LESSON, FakeProd, _gid, _grade_row, _local, _put_local, copy  # noqa: F401

STUDENTS = ("stud:s1", "stud:s2", "stud:s3")
VALUES = ("2", "3", "4", "5")
#Правка человека иногда СНИМАЕТ оценку ("") — надгробие: строка остаётся с deleted=1.
LOCAL_VALUES = VALUES + ("",)


def _tomb(value, sid):
    """Строка оценки, как её хранит бой: пустое значение — надгробие."""
    row = _grade_row(value, 0, sid=sid)
    row["deleted"] = value == ""
    return row
STEPS = 30


def _token(login: str) -> str:
    """Токен, у которого читается только `sub` — так его читает `desk_outbox`."""
    part = base64.urlsafe_b64encode(json.dumps({"sub": login}).encode()).decode().rstrip("=")
    return f"h.{part}.s"


class Prod(FakeProd):
    """Бой, который принимает запись оценки по контракту `write.py`."""

    def __init__(self, rnd: random.Random, net_faults: bool):
        super().__init__()
        self.rnd = rnd
        self.net_faults = net_faults
        self.applied = set()          #номера правок, которые бой принял
        self.versions = {}            #номер правки → сколько версий строки она породила
        self.owner = {}               #номер правки → чья она
        self.seen = {"down": 0, "lost": 0, "drop": 0, "reset": 0, "restore": 0, "tomb": 0}
        self.backups = []
        #Якорь вне базы (`sync_clock.check_restore`): наибольший номер, который бой уже
        #выдал. В модели он не отстаёт — окно отставания на бою (30 с) короче суток между
        #снимками, и сюда его не тащим, чтобы не выдавать известную границу за дефект.
        self.anchor = 0
        self.rolled_back = set()      #правки, которые бой потерял при восстановлении

    def send(self, method, url, body, headers):
        data = json.loads(body)
        who = desk_outbox.token_subject(headers["Authorization"].split()[-1])
        #Оценка, возвращённая человеком из карантина восстановления, номера правки не
        #несёт: это не новая правка, а старая версия строки. Её владелец — тот же t1.
        eid = data.get("_edit")
        owner = self.owner[eid] if eid is not None else "t1"
        #Инвариант 5 — на КАЖДОЙ отправке, а не в конце.
        assert who == owner, f"правка {eid} ({owner}) ушла токеном {who}"
        if self.net_faults and self.rnd.random() < 0.2:
            self.seen["down"] += 1
            return 0, {"detail": "ConnectError"}               #обрыв ДО записи
        key = _gid(data["student_id"], data["lesson_id"])
        cur = self.rows.get(("grades", key))
        value, cleared = data["grade"], data["grade"] == ""
        #`differs` из `write.py`: и значение, и отметка снятия (надгробие — тоже версия).
        differs = cur is not None and ((cur["grade"] or "") != value
                                       or bool(cur.get("deleted")) != cleared)
        if differs and "base_seq" in data:
            if int(cur["change_seq"]) != int(data["base_seq"] or 0):
                return 409, {"detail": {"code": "conflict", "id": key,
                                        "server_seq": cur["change_seq"]}}
        if cur is None or differs:
            seq = self.put("grades", _tomb(value, data["student_id"]))
            self.versions[eid] = self.versions.get(eid, 0) + 1
        else:
            seq = int(cur["change_seq"])                       #то же значение — не запись
        if eid is not None:
            self.applied.add(eid)
        if self.net_faults and self.rnd.random() < 0.25:
            self.seen["lost"] += 1
            return 0, {"detail": "ReadTimeout"}                #записано, ответ потерян
        return 200, {"id": key, "updated_at": f"P{seq}", "change_seq": seq}

    def put(self, table, row):
        seq = super().put(table, row)
        self.anchor = max(self.anchor, seq)
        return seq

    def outside_edit(self):
        sid = self.rnd.choice(STUDENTS)
        roll = self.rnd.random()
        if roll < 0.1:
            self.seen["drop"] += 1
            self.drop("grades", _gid(sid, LESSON))
        elif roll < 0.25:
            self.seen["tomb"] += 1
            self.put("grades", _tomb("", sid))
        else:
            self.put("grades", _grade_row(self.rnd.choice(VALUES), 0, sid=sid))

    def take_backup(self):
        self.backups.append(_copy.deepcopy((self.rows, self.deletes, self.head, self.applied)))

    def restore(self):
        if not self.backups:
            return
        self.seen["restore"] += 1
        rows, deletes, head, applied = _copy.deepcopy(self.rnd.choice(self.backups))
        self.rolled_back |= self.applied - applied
        self.rows, self.deletes, self.applied = rows, deletes, applied
        #Поколение меняет администратор (`--new-epoch`) или сам бой по якорю: база моложе
        #уже выданного. Иначе — снимок равен якорю, после него не выдано ничего, и
        #нумерация честно продолжается с того же места.
        if self.rnd.random() < 0.5 or head < self.anchor:
            self.epoch = f"E{self.rnd.random():.6f}"
            self.head = max(self.anchor, head) + 1000      #перескок номеров, как на бою
        else:
            self.head = head

    def scope_reset(self):
        self.seen["reset"] += 1
        self.scope = "S2" if self.scope == "S1" else "S1"


def _put_local_tomb(value, seq, sid):
    """Правка в копии так, как её делает обработчик: снятие — надгробие, не удаление."""
    from app.db import SessionLocal
    from app.models import Grade
    db = SessionLocal()
    try:
        data = _tomb(value, sid)
        data["change_seq"] = seq
        db.merge(Grade(**data))
        db.commit()
    finally:
        db.close()


class Model:
    def __init__(self, seed: int, outside: bool, net_faults: bool):
        self.rnd = random.Random(seed)
        self.prod = Prod(self.rnd, net_faults)
        self.outside = outside
        self.edits = 0
        self.at_screen = "t1"         #кто сейчас за компьютером
        self.latest = {}              #ключ → значение, которое человек видит на экране
        self.dropped = set()          #правки, от которых человек отказался сам
        self.conflicts = 0
        self.orphans = 0
        self.trace = []               #история переходов — в текст любого красного

    def _auth(self):
        return "https://prod.test", _token(self.at_screen), ""

    # ── переходы ─────────────────────────────────────────────────────────────────────
    def local_edit(self, crash: bool = False):
        if self.at_screen != "t1":
            return
        sid, value = self.rnd.choice(STUDENTS), self.rnd.choice(LOCAL_VALUES)
        self.edits += 1
        self.prod.owner[self.edits] = "t1"
        body = {"surname": "Иванов", "name": "Иван", "lesson_id": LESSON, "grade": value,
                "student_id": sid, "_edit": self.edits}
        seq = desk_outbox.enqueue("t1", "POST", "/web/teacher/grade", "",
                                  json.dumps(body).encode(), "application/json")
        if crash and self.rnd.random() < 0.5:
            self.orphans += 1
            return                    #упали ДО записи в копию: на экране прежнее
        before = _local(key=_gid(sid, LESSON))
        base_seq = int(before[1] or 0) if before else 0
        _put_local_tomb(value, base_seq, sid)                  #копия — сразу (обработчик)
        self.latest[_gid(sid, LESSON)] = value
        if crash:
            self.orphans += 1
            return                    #упали ПОСЛЕ записи, ответа обработчика нет
        desk_outbox.mark_ready(seq, {"id": _gid(sid, LESSON), "base_updated_at": "",
                                     "base_seq": base_seq, "updated_at": f"L{self.edits}"})

    def crash_edit(self):
        self.local_edit(crash=True)

    def flush(self):
        #Фоновая досылка живёт своим циклом и может ещё держать очередь ПРЕЖНЕГО человека.
        res = desk_outbox.flush(login="t1", auth=self._auth, send=self.prod.send)
        if self.at_screen != "t1":
            #Отправок нет; «account-switch» — если было что слать (без готовых правок
            #досылка выходит раньше проверки токена, и это верно: слать нечего).
            assert res["sent"] == 0 and res["stopped"] in ("account-switch", ""), res
        self.conflicts += res["conflicts"]

    def mirror(self):
        res = local_mirror.mirror_once(client=self.prod)
        if desk_outbox.take_rebuild_request():
            res = local_mirror.rebuild(client=self.prod)
        self.check_screen_keeps_own_edits()
        if res.get("ok") and not (res.get("deferred") or res.get("busy")):
            self.check_cursor_is_honest()

    def decide(self, keep_mine=None):
        for p in desk_outbox.problems("t1"):
            mine = self.rnd.random() < 0.5 if keep_mine is None else keep_mine
            #Возврат из карантина номера правки не несёт: это не новая правка человека.
            if not mine and p["sent"].get("_edit") is not None:
                self.dropped.add(p["sent"]["_edit"])
            desk_outbox.resolve(p["seq"], "t1", "keep_mine" if mine else "keep_server")

    def switch_account(self):
        self.at_screen = "t2" if self.at_screen == "t1" else "t1"
        if self.at_screen == "t2":
            #Новый человек не видит чужой очереди и не получает её на подпись.
            assert desk_outbox.problems("t2") == [] and not desk_outbox.has_unsent("t2")
            assert desk_outbox.pending_keys("t2") == set()

    def step(self):
        actions = ([self.local_edit] * 4 + [self.crash_edit] + [self.flush] * 3
                   + [self.mirror] * 2 + [self.decide] + [self.switch_account])
        if self.outside:
            actions += ([self.prod.outside_edit] * 2 + [self.prod.scope_reset]
                        + [self.prod.take_backup, self.prod.restore])
        act = self.rnd.choice(actions)
        self.trace.append(act.__name__)
        act()

    # ── инварианты на каждом шаге ────────────────────────────────────────────────────
    def check_screen_keeps_own_edits(self):
        for tbl, key in desk_outbox.pending_keys("t1"):
            if tbl == "grades" and key in self.latest:
                row = _local(key=key)
                assert row is not None and row[0] == self.latest[key], \
                    f"зеркало откатило правку на экране: {key} {row} ≠ {self.latest[key]}"

    def check_cursor_is_honest(self):
        cursor = int(local_mirror.state().get("cursor") or 0)
        guarded = {k for _t, k in desk_outbox.pending_keys("t1")}
        for (tbl, key), row in self.prod.rows.items():
            if tbl != "grades" or key in guarded or row["change_seq"] > cursor:
                continue
            local = _local(key=key)
            assert local is not None and int(local[1] or 0) >= row["change_seq"], (
                f"курсор {cursor} пройден, а правка боя {key}@{row['change_seq']} не доехала: "
                f"{local}; история: {self.trace}")
            if int(local[1] or 0) == row["change_seq"]:
                assert local[0] == row["grade"], (key, local, row)
        for seq, tbl, key in self.prod.deletes:
            if (tbl == "grades" and seq <= cursor and key not in guarded
                    and ("grades", key) not in self.prod.rows):
                local = _local(key=key)
                assert local is None or int(local[1] or 0) > seq, \
                    f"курсор {cursor} пройден, а удаление {key}@{seq} не доехало: {local}"

    def settle_quarantine(self):
        for q in desk_outbox.quarantined("t1"):
            desk_outbox.release_quarantined(
                q["id"], "t1", "return" if self.rnd.random() < 0.5 else "dismiss")

    def drain(self):
        """Сеть починилась, человек вернулся и разобрал конфликты — довести до покоя."""
        self.prod.net_faults = False
        self.at_screen = "t1"
        for _ in range(20):
            self.flush()
            self.decide()
            self.mirror()
            self.settle_quarantine()
            if not desk_outbox.has_unsent("t1") and not desk_outbox.quarantined("t1"):
                break
        assert not desk_outbox.has_unsent("t1"), "очередь не опустела при живой сети"
        self.mirror()
        local_mirror.rebuild(client=self.prod)


@pytest.fixture()
def orphans_go_out(monkeypatch):
    #Сирота уходит в досылку сразу, а не через ORPHAN_AFTER_S: в модели время не идёт.
    monkeypatch.setattr(desk_outbox, "ORPHAN_AFTER_S", -1)


def _run(seed: int, outside: bool, net_faults: bool = True) -> Model:
    m = Model(seed, outside, net_faults)
    for _ in range(STEPS):
        m.step()
    m.drain()
    return m


@pytest.mark.parametrize("seed", range(12))
def test_random_histories_lose_nothing_and_converge(copy, orphans_go_out, seed):  # noqa: F811
    m = _run(seed, outside=True)
    lost = set(range(1, m.edits + 1)) - m.prod.applied - m.dropped - m.prod.rolled_back
    assert not lost, f"seed={seed}: правки потеряны молча: {sorted(lost)}"
    for sid in STUDENTS:
        key = _gid(sid, LESSON)
        prod_row = m.prod.rows.get(("grades", key))
        local = _local(key=key)
        assert (local[0] if local else None) == (prod_row["grade"] if prod_row else None), \
            f"seed={seed}: копия разошлась с боем по {key}: {local} ≠ {prod_row}"
    from sync import verifier
    res = verifier.verify(m.prod)
    assert res["ok"] and not res["mismatch"], f"seed={seed}: Сверщик не подтвердил: {res}"


@pytest.mark.parametrize("seed", range(8))
def test_retries_after_lost_answers_never_conflict_or_write_twice(copy, orphans_go_out,  # noqa: F811
                                                                    seed):
    m = _run(100 + seed, outside=False)
    assert m.conflicts == 0, f"seed={100 + seed}: повтор поспорил сам с собой"
    assert set(range(1, m.edits + 1)) <= m.prod.applied
    twice = {e: n for e, n in m.prod.versions.items() if n > 1}
    assert not twice, f"seed={100 + seed}: повтор породил вторую версию строки: {twice}"


def test_histories_reach_the_hard_states(copy, orphans_go_out):  # noqa: F811
    """Зелёная модель ничего не доказывает, если случайные истории не доходят до трудных
    состояний. Проверяем, что они там бывают: обрыв, потерянный ответ, удаление и сброс
    области на бою, сирота, конфликт, оба решения человека и смена учётной записи."""
    seen = {"down": 0, "lost": 0, "drop": 0, "reset": 0, "restore": 0, "tomb": 0,
            "conflicts": 0, "dropped": 0, "orphans": 0}
    for seed in range(4):
        m = _run(seed, outside=True)
        for k in ("down", "lost", "drop", "reset", "restore", "tomb"):
            seen[k] += m.prod.seen[k]
        seen["conflicts"] += m.conflicts
        seen["dropped"] += len(m.dropped)
        seen["orphans"] += m.orphans
    assert all(seen.values()), seen


def test_the_model_can_see_a_lost_edit(copy, orphans_go_out):  # noqa: F811
    """Обратный ход самой модели: бой, который «теряет» запись молча (отвечает 200, но не
    пишет), свойство 2 обязано поймать — иначе модель зелена при любом коде."""
    m = Model(7, outside=False, net_faults=False)
    honest = m.prod.send

    def lying(method, url, body, headers):
        data = json.loads(body)
        if data["_edit"] == 1:
            return 200, {"id": _gid(data["student_id"], LESSON), "updated_at": "P0",
                         "change_seq": 0}
        return honest(method, url, body, headers)

    m.prod.send = lying
    m.local_edit()
    m.local_edit()
    m.drain()
    assert 1 not in m.prod.applied and 1 not in m.dropped
