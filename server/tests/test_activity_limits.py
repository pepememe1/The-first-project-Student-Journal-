"""
test_activity_limits.py — тормоз частоты и предел размера штриха в активностях
(адверсариальный разбор 18.08.2026).

Что здесь закрывается и почему это НЕ теория:

  1. У активностей не было ограничения частоты НИ ОДНОГО, при том что у сообщений оно
     есть с 2.9.1. Разница не в объёме, а в УСИЛЕНИИ: `POST /{id}/progress` — один дешёвый
     запрос от студента, а на выходе кадр ВСЕМ участникам беседы плюс три запроса в базу у
     ведущего. В канале на сотню человек это стократное усиление, и особых прав для него
     не нужно — достаточно быть участником.

  2. У штриха доски было ограничено ЧИСЛО, но не размер. Штрих — непрозрачный для сервера
     словарь (и должен таким быть: формат объектов доски расширялся уже дважды), поэтому
     20000 разрешённых штрихов могли весить сколько угодно, а лежат они В ПАМЯТИ процесса
     на машине с 960 МБ.

⚠️ У каждой проверки есть ОБРАТНАЯ. Тормоз, который душит обычное рисование, и фильтр,
режущий настоящие штрихи, прошли бы прямые проверки и сломали бы продукт молча — а
доска ломается не падением, а тем, что линия не появилась у остальных.
"""
from conftest import make_admin, make_teacher
from test_messenger import _make_student

from app import msg_limit

A = "/web/messenger/activities"


def _setup(client):
    admin = make_admin(client)
    t = make_teacher(client, admin)
    b_id, b = _make_student(client, admin, "bob", "Боб Бобов")
    return admin, ("teach:teacher1", t), (b_id, b)


def _board(client, headers, member_ids):
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Пара", "member_ids": member_ids},
                       headers=headers).json()["conversation_id"]
    r = client.post(f"{A}/start", headers=headers,
                    json={"conversation_id": conv, "kind": "board", "params": {}})
    assert r.status_code == 200, r.text
    return conv, r.json()["id"]


def _stroke(points=8):
    """Правдоподобный штрих: кусок линии за ~150 мс — это единицы точек, не сотни."""
    return {"g": "g1", "type": "pen", "color": "#222", "w": 3,
            "pts": [[i, i * 2] for i in range(points)]}


# ── Тормоз частоты ───────────────────────────────────────────────────────────────────
def test_progress_spam_is_slowed_down(client):
    """Усилитель закрыт: бесконечно дёргать шкалу прогресса нельзя."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Пара", "member_ids": [b_id]},
                       headers=t).json()["conversation_id"]
    quiz = client.post(f"{A}/quizzes", headers=t, json={
        "title": "Т", "questions": [{"type": "single", "text": "2+2?", "points": 1,
                                     "options": [{"text": "4", "is_correct": True},
                                                 {"text": "5"}]}]}).json()["id"]
    act = client.post(f"{A}/start", headers=t,
                      json={"conversation_id": conv, "kind": "quiz",
                            "params": {"quiz_id": quiz}}).json()["id"]

    codes = [client.post(f"{A}/{act}/progress", json={"answered": 1}, headers=b).status_code
             for _ in range(40)]
    assert 429 in codes, "шкалу прогресса можно дёргать без предела — усилитель открыт"
    first_429 = codes.index(429)
    assert first_429 >= 20, (
        f"тормоз сработал на {first_429}-м запросе — это уже мешало бы живому прохождению")


def test_the_slowdown_names_the_wait(client):
    """429 обязан сказать, СКОЛЬКО ждать: без `Retry-After` клиенту остаётся гадать,
    и обычная реализация «повторим сразу» превращает тормоз в бесконечный цикл."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Пара", "member_ids": [b_id]},
                       headers=t).json()["conversation_id"]
    quiz = client.post(f"{A}/quizzes", headers=t, json={
        "title": "Т", "questions": [{"type": "single", "text": "2+2?", "points": 1,
                                     "options": [{"text": "4", "is_correct": True}]}]}).json()["id"]
    act = client.post(f"{A}/start", headers=t,
                      json={"conversation_id": conv, "kind": "quiz",
                            "params": {"quiz_id": quiz}}).json()["id"]
    last = None
    for _ in range(40):
        last = client.post(f"{A}/{act}/progress", json={"answered": 1}, headers=b)
        if last.status_code == 429:
            break
    assert last.status_code == 429
    assert int(last.headers.get("Retry-After", 0)) >= 1


def test_normal_drawing_is_not_slowed_down(client):
    """ОБРАТНЫЙ ХОД, и он здесь главный.

    Клиент шлёт хвост линии кусками раз в ~150 мс (§7 плана) — это ~7 запросов в секунду
    непрерывно, пока человек ведёт пером. Тормоз, поставленный «на глазок» в 10 запросов
    за 10 секунд, прошёл бы проверку выше и при этом рвал бы КАЖДУЮ длинную линию у доски,
    причём молча: у остальных участников просто не появился бы кусок."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv, act = _board(client, t, [b_id])
    codes = [client.post(f"{A}/{act}/strokes", json={"strokes": [_stroke()]},
                         headers=t).status_code
             for _ in range(70)]           #~10 секунд непрерывного рисования
    assert 429 not in codes, "тормоз рвёт обычное рисование — это хуже, чем его отсутствие"


def test_activity_actions_do_not_eat_the_message_quota(client):
    """Счётчики РАЗДЕЛЬНЫЕ.

    Общий счётчик с сообщениями выглядел бы экономией кода, а на деле означал бы, что
    студент, быстро отвечающий на вопросы соревнования, теряет право писать в чат — игра
    затыкала бы переписку, и связь между этими двумя вещами не угадал бы никто."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv, act = _board(client, t, [b_id])
    for _ in range(60):
        client.post(f"{A}/{act}/strokes", json={"strokes": [_stroke()]}, headers=t)
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": "привет"}, headers=t)
    assert r.status_code == 200, (
        "рисование на доске выбрало квоту на сообщения — счётчики склеены")


def test_reset_clears_the_new_counters():
    """⚠️ Грабля, на которой этот проект уже обжигался (`throttle.reset()` не чистил
    `_recover`): новый словарь состояния обязан попадать в `reset()`, иначе тесты
    становятся зависимыми от порядка — проходят в одиночку и падают в общем прогоне."""
    msg_limit.reset()
    for _ in range(200):
        msg_limit.bucket_check("progress", "u1")
    assert msg_limit.bucket_check("progress", "u1") > 0
    msg_limit.reset()
    assert msg_limit.bucket_check("progress", "u1") == 0


# ── Размер штриха ────────────────────────────────────────────────────────────────────
def test_a_stroke_that_cannot_be_real_is_dropped(client):
    """Штрих на мегабайт в состояние не попадает."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv, act = _board(client, t, [b_id])
    fat = {"g": "g1", "type": "pen", "junk": "х" * 200_000}
    r = client.post(f"{A}/{act}/strokes", json={"strokes": [fat]}, headers=t)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0, "штрих на 200 КБ осел в памяти процесса"


def test_a_real_stroke_still_gets_through(client):
    """ОБРАТНЫЙ ХОД: фильтр, режущий всё подряд, прошёл бы проверку выше и оставил бы
    доску пустой — при совершенно исправном на вид сервере."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv, act = _board(client, t, [b_id])
    r = client.post(f"{A}/{act}/strokes",
                    json={"strokes": [_stroke(), _stroke(60)]}, headers=t)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2, "обычные штрихи не доехали до доски"


def test_one_bad_stroke_does_not_take_the_good_ones_with_it(client):
    """Режем ПОШТУЧНО: одна испорченная точка не должна стирать линию, нарисованную рядом
    в той же пачке. Отказ всей пачке выглядел бы для человека как пропавший кусок."""
    msg_limit.reset()
    admin, (t_id, t), (b_id, b) = _setup(client)
    conv, act = _board(client, t, [b_id])
    r = client.post(f"{A}/{act}/strokes",
                    json={"strokes": [_stroke(), {"junk": "х" * 200_000}, _stroke()]},
                    headers=t)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2
