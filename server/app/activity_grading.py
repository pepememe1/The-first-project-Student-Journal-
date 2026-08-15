"""
activity_grading.py — проверка ответов викторины. ЕДИНСТВЕННОЕ место, где это делается.

🔒 Проверка живёт на СЕРВЕРЕ, и это не перестраховка. Чтобы проверить ответ у себя,
клиенту нужен ключ (какой вариант верный) — а любой студент откроет инструменты
разработчика и прочитает его до начала. Поэтому вопросы уезжают к студенту БЕЗ ключа
(`routers/activities._question_out(..., with_key=False)`), а сюда приходят его ответы.

Почему один модуль, а не метод внутри роутера: правил проверки четыре (по типу задания),
и их зовут ДВА разных режима — асинхронная викторина (все ответы одним запросом) и
синхронное соревнование (по одному вопросу). Вторая копия правил разошлась бы с первой,
и один и тот же ответ считался бы верным в викторине и неверным в соревновании. Тот же
принцип, что у `grading.py` для оценок (инвариант §8 CLAUDE.md).

Формат ответа участника (одинаковый для обоих режимов), по типу вопроса:
    single — id выбранного варианта (строка)
    multi  — список id выбранных вариантов
    order  — список id вариантов В ТОМ ПОРЯДКЕ, как их расставил человек
    match  — {id варианта: выбранный ключ сопоставления}
"""

#Верхняя доля надбавки за скорость в СОРЕВНОВАНИИ: мгновенный верный ответ стоит
#1.5 балла там, где неспешный верный стоит 1. Надбавка именно ДОЛЯ от очков вопроса, а не
#фиксированные баллы: иначе на дорогом вопросе скорость ничего не решала бы, а на дешёвом
#решала бы всё. В асинхронной викторине надбавки нет вовсе — там человек идёт своим
#темпом, и торопить его нечем и незачем.
SPEED_BONUS_MAX = 0.5


def check_answer(question, options: list, answer) -> bool:
    """Верен ли ответ на ОДИН вопрос. `options` — все варианты этого вопроса.

    ⚠️ Частично верный ответ считается НЕВЕРНЫМ (`multi`/`order`/`match` — всё или
    ничего). Это осознанный выбор, а не упрощение: доля правильного в «расставьте по
    порядку» не определена однозначно (два соседних элемента местами — это ошибка одна
    или две?), и любая формула здесь была бы спором с преподавателем, которому нечем её
    проверить. Соревнование по той же причине допускает только single/multi (§8.5)."""
    qtype = (getattr(question, "type", "") or "single").strip()
    if qtype == "single":
        correct = [o.id for o in options if o.is_correct]
        return bool(correct) and str(answer or "") == correct[0]
    if qtype == "multi":
        if not isinstance(answer, (list, tuple, set)):
            return False
        correct = {o.id for o in options if o.is_correct}
        #Пустой ключ (преподаватель не отметил ни одного верного варианта) не должен
        #делать верным пустой ответ — иначе недозаполненный вопрос все проходят даром.
        return bool(correct) and set(str(a) for a in answer) == correct
    if qtype == "order":
        if not isinstance(answer, (list, tuple)):
            return False
        placed = [str(a) for a in answer]
        if len(placed) != len(options):
            return False
        by_id = {o.id: o for o in options}
        for idx, oid in enumerate(placed, start=1):
            opt = by_id.get(oid)
            if opt is None or int(opt.correct_position or 0) != idx:
                return False
        return True
    if qtype == "match":
        if not isinstance(answer, dict):
            return False
        #Сопоставить нужно ВСЕ пары: пропущенная — это несделанное задание, а не «почти».
        for opt in options:
            if str(answer.get(opt.id, "")) != (opt.match_key or ""):
                return False
        return True
    return False


def grade(questions: list, options_by_question: dict, answers: dict) -> dict:
    """Проверить весь набор. Возвращает {score, correct_count, total_count, per_question}.

    `per_question` — [{question_id, correct, points}] для разбора: без него студент видит
    только цифру и не понимает, где ошибся, а преподаватель не может показать разбор."""
    per_question, score, correct_count = [], 0.0, 0
    for q in questions:
        opts = options_by_question.get(q.id, [])
        ok = check_answer(q, opts, (answers or {}).get(q.id))
        pts = float(q.points or 1) if ok else 0.0
        if ok:
            correct_count += 1
        score += pts
        per_question.append({"question_id": q.id, "correct": ok, "points": pts})
    return {"score": round(score, 2), "correct_count": correct_count,
            "total_count": len(questions), "per_question": per_question}


def speed_score(points: float, elapsed_ms: int, limit_ms: int) -> float:
    """Баллы за ВЕРНЫЙ ответ в соревновании с учётом скорости.

    Ответ в первый момент — `points * (1 + SPEED_BONUS_MAX)`, ответ на последней секунде —
    ровно `points`. Неверный ответ сюда не попадает вовсе (ноль есть ноль, и торопиться
    ошибаться незачем)."""
    base = float(points or 1)
    if limit_ms <= 0:
        return round(base, 2)
    left = max(0.0, min(1.0, 1.0 - (max(0, int(elapsed_ms)) / float(limit_ms))))
    return round(base * (1.0 + SPEED_BONUS_MAX * left), 2)
