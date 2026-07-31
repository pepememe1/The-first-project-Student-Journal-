"""
rustore_push.py — отправка пуш-уведомлений через RuStore Push.

Почему RuStore, а не FCM. Приложение раздаётся через RuStore, и на части телефонов
российской аудитории сервисов Google просто нет — FCM там молчит без единой ошибки.
RuStore Push работает на тех же устройствах, где установлено само приложение.

⚠️ ЧТО КЛАДЁМ В УВЕДОМЛЕНИЕ (152-ФЗ). Тело пуша проходит через серверы RuStore, то
есть через третью сторону. Поэтому в нём НЕТ ни оценки, ни предмета, ни ФИО — только
факт «у вас новая оценка». Успеваемость конкретного студента — персональные данные, и
отдавать её посреднику незачем: приложение открывается и забирает детали у нашего
сервера по защищённому каналу.

Секреты (project_id, сервисный токен) берутся ТОЛЬКО из окружения — см. config.py.
Не настроены → функции возвращают 0 отправленных и молчат: сервер обязан работать
и без пушей, это дополнение, а не условие.
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config

log = logging.getLogger("gradebook.push")

#Официальный адрес RuStore Push API. Вынесен в константу: при смене версии API правка
#в одном месте, а не по всему файлу.
API_URL = "https://vkpns.rustore.ru/v1/projects/{project_id}/messages:send"
TIMEOUT_S = 8

#Сколько подряд неудач терпим у токена, прежде чем считать устройство мёртвым.
#RuStore не сообщает об удалении приложения — молчание единственный признак.
MAX_FAILS = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post(payload: dict) -> tuple:
    """Запрос к RuStore. Возвращает (успех, код_ответа, текст). Исключений не бросает:
    падение пуша НЕ должно ронять выставление оценки."""
    url = API_URL.format(project_id=config.RUSTORE_PROJECT_ID)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {config.RUSTORE_SERVICE_TOKEN}",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return True, r.status, r.read().decode("utf-8", "replace")[:500]
    except urllib.error.HTTPError as e:
        return False, e.code, e.read().decode("utf-8", "replace")[:500]
    except Exception as e:
        return False, 0, str(e)[:500]


def send_to_token(token: str, title: str, body: str, data: dict | None = None) -> tuple:
    """Одно уведомление на одно устройство. (успех, код, ответ)."""
    payload = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            #data доезжает в приложение и решает, КУДА открыть экран. Персональных
            #данных здесь тоже нет — только тип события.
            "android": {"data": {k: str(v) for k, v in (data or {}).items()}},
        }
    }
    return _post(payload)


#──────────────────────────────────────────────────────────────────────────────────────
#КАТЕГОРИИ УВЕДОМЛЕНИЙ и их отключение пользователем.
#
#Категория выводится из УЖЕ существующего `data["type"]`, который передают все без
#исключения вызывающие. Второго списка «кто что шлёт» заводить нельзя: он неминуемо
#разъедется с первым, и человек, отключивший оценки, продолжил бы их получать.
#
#Неизвестный тип — РАЗРЕШАЕМ. Ошибка в пользу тишины опаснее: новый вид уведомления
#молча не доходил бы до всех, и заметить это можно было бы только случайно.
CATEGORY_BY_TYPE = {
    "grade": "grades",
    "grade_changed": "grades",
    "homework": "homework",
    "schedule_changed": "schedule",
    "event": "events",
    "reminder": "reminders",
    "message": "messages",
}

#Все категории, которыми можно управлять из настроек. Клиент рисует свои подписи —
#здесь только ключи, чтобы не держать тексты в двух местах.
ALL_CATEGORIES = ("grades", "homework", "schedule", "messages", "events", "reminders")


def category_of(data: dict | None) -> str:
    """Категория уведомления по его полезной нагрузке ('' — не определена)."""
    kind = str((data or {}).get("type") or "").strip()
    return CATEGORY_BY_TYPE.get(kind, "")


def category_enabled(prefs: dict | None, category: str) -> bool:
    """Разрешил ли человек уведомления этой категории.

    ОТСУТСТВИЕ ключа значит «да». Настройки приезжают из синка и от старых клиентов,
    где раздела уведомлений не было вовсе — трактовать пустоту как запрет означало бы
    молча выключить пуши всему колледжу при первом же обновлении."""
    if not category:
        return True
    box = (prefs or {}).get("notify")
    if not isinstance(box, dict) or category not in box:
        return True
    return bool(box.get(category))


def _muted_categories(db, login: str) -> set:
    """Категории, отключённые этим пользователем. Сбой чтения — считаем, что не отключал
    ничего: потерять уведомление хуже, чем прислать лишнее."""
    try:
        from .models import User
        row = db.query(User).filter(User.login == login).first()
        prefs = (row.prefs if row is not None else None) or {}
    except Exception as e:      # noqa: BLE001
        log.warning("не удалось прочитать настройки уведомлений: %s", e)
        return set()
    return {c for c in ALL_CATEGORIES if not category_enabled(prefs, c)}


def notify_login(db, login: str, title: str, body: str, data: dict | None = None) -> int:
    """Разослать на ВСЕ устройства пользователя. Возвращает число успешных отправок.

    Не бросает исключений ВООБЩЕ, и это проверяется тестом: функция вызывается из
    обработчика выставления оценки, и сбой доставки не должен мешать преподавателю
    поставить балл. Раньше обещание было только в докстринге — исключение из
    send_to_token проходило наружу и роняло запрос.

    ⚠️ ЗДЕСЬ ЖЕ единственная проверка «человек отключил эту категорию». Ставить её у
    вызывающих нельзя: пуш отправляется из восьми мест, и достаточно забыть про одно,
    чтобы отключённые уведомления продолжали приходить. Письмо во вкладке
    «Уведомления» при этом ОСТАЁТСЯ: отключается то, что дёргает человека, а не история
    произошедшего — иначе студент, приглушивший телефон, потерял бы факт оценки."""
    if not config.push_enabled():
        return 0
    category = category_of(data)
    if category and category in _muted_categories(db, login):
        return 0
    try:
        from .models import PushToken
        rows = db.query(PushToken).filter(PushToken.login == login).all()
    except Exception as e:
        log.warning("не удалось прочитать токены устройств: %s", e)
        return 0

    sent = 0
    for row in rows:
        #ЛОВИМ ВСЁ. _post обрабатывает свои ошибки сам, но защищаться надо от любых:
        #сюда приходят чужой SDK, сеть и БД, а обещание «пуш не мешает поставить
        #оценку» должно выполняться буквально, а не «обычно».
        try:
            ok, code, text = send_to_token(row.token, title, body, data)
        except Exception as e:
            log.warning("отправка пуша упала: %s", e)
            continue
        if ok:
            row.fail_count = 0
            sent += 1
            continue
        #404/400 у RuStore — токен недействителен (приложение удалили/переустановили).
        #Такую запись убираем сразу, не дожидаясь счётчика: она уже не оживёт.
        if code in (400, 404):
            log.info("токен устройства недействителен, удаляю (%s)", code)
            db.delete(row)
            continue
        row.fail_count = (row.fail_count or 0) + 1
        log.warning("пуш не доставлен (код %s, попытка %s): %s", code, row.fail_count, text)
        if row.fail_count >= MAX_FAILS:
            log.info("устройство молчит %s раз подряд — убираю токен", MAX_FAILS)
            db.delete(row)
    try:
        db.commit()
    except Exception as e:
        log.warning("не удалось сохранить состояние токенов: %s", e)
        db.rollback()
    return sent


#──────────────────────────────────────────────────────────────────────────────────────
#ТЕКСТЫ ПИСЕМ для вкладки «Уведомления».
#
#⚠️ НЕ ПУТАТЬ С ТЕКСТОМ ПУША. В пуш через серверы RuStore уходит только нейтральное
#«у вас новая оценка» — без балла, предмета и ФИО (см. шапку модуля). Тексты ниже
#хранятся в НАШЕЙ базе и показываются уже вошедшему пользователю по защищённому каналу,
#поэтому здесь балл и предмет называть можно — без них письмо бессмысленно.

#Посещаемость приезжает тем же полем, что и балл (Н/Б/О).
_ATTENDANCE = {"Н": "неявка", "Б": "болезнь", "О": "уважительная причина"}


def _subject_phrase(subject: str) -> str:
    return f" по предмету «{subject}»" if subject else ""


def _new_grade_words(value: str, subject: str) -> tuple:
    """(заголовок, тело) письма о новой оценке. Тон зависит от балла.

    На двойке намеренно НЕ ругаем. Уведомление читает подросток, и упрёк из приложения
    оценку не исправит — он научит только отключать уведомления. Поэтому вместо
    недовольства даём понятный следующий шаг."""
    v = (value or "").strip()
    where = _subject_phrase(subject)
    if v in _ATTENDANCE:
        return ("Отмечено посещение",
                f"Преподаватель отметил{where}: {_ATTENDANCE[v]} ({v}).")
    if v == "5":
        return ("Отличная оценка!", f"Вам поставили 5{where}. Так держать!")
    if v == "4":
        return ("Хорошая оценка", f"Вам поставили 4{where}. Хороший результат!")
    if v == "3":
        return ("Новая оценка",
                f"Вам поставили 3{where}. Есть куда расти — разберите тему, "
                "и следующая будет выше.")
    if v == "2":
        return ("Новая оценка",
                f"Вам поставили 2{where}. Не откладывайте: подойдите к преподавателю "
                "и спросите, как её исправить.")
    return ("Новая оценка",
            f"Вам поставили оценку {v}{where}." if v else f"У вас новая оценка{where}.")


def _changed_grade_words(old: str, new: str, subject: str) -> tuple:
    return ("Оценка изменена",
            f"Оценка {old} изменена на {new}{_subject_phrase(subject)}. "
            "Если этого не ожидали — перепроверьте у преподавателя.")


def _schedule_words(role: str, group: str) -> tuple:
    """Тон зависит от роли — так просил заказчик: студенту по-дружески, преподавателю
    официально."""
    who = f" группы {group}" if group else ""
    if role == "student":
        return ("Расписание изменилось",
                f"Эй! У тебя поменялось расписание{who} — загляни и проверь, "
                "а то придёшь в выходной 😄")
    return ("Изменение в расписании",
            f"Здравствуйте! Расписание{who} изменилось. Просим вас сверить занятия.")


def _create_event(db, login: str, kind: str, title: str, body: str,
                  subject: str = "", lesson_id: str = "", payload: dict | None = None,
                  author_login: str = "", batch_id: str = "") -> str:
    """Сохраняет событие и возвращает его id ("" — если сохранить не удалось).

    Пустой id не отменяет отправку пуша: человек всё равно узнает, что что-то новое
    есть, просто без адресного перехода. Терять уведомление из-за сбоя записи хуже."""
    import uuid
    from .models import NotifyEvent
    event_id = str(uuid.uuid4())
    try:
        db.add(NotifyEvent(id=event_id, login=login, kind=kind,
                           subject=subject or "", lesson_id=lesson_id or "",
                           title=title, body=body, payload=payload or {},
                           author_login=author_login or "", batch_id=batch_id or "",
                           created_at=_now_iso()))
        db.commit()
    except Exception as e:
        log.warning("не удалось сохранить событие уведомления: %s", e)
        db.rollback()
        return ""
    return event_id


def notify_new_grade(db, login: str, subject: str = "", lesson_id: str = "",
                     value: str = "") -> int:
    """Уведомление студенту о новой оценке + событие для перехода в нужный журнал.

    Текст ПУША намеренно без балла, предмета и ФИО: он идёт через посредника (см. шапку
    модуля). В пуш уезжает только id события; подробности приложение получит от НАС,
    открывшись. Побочный выигрыш: если токен входа сгорел, приложение запомнит id,
    покажет вход и совершит переход после него — событие не потеряется.

    `value` необязателен: без него письмо будет обезличенным («у вас новая оценка»),
    но ничего не сломается — так вызывали эту функцию раньше."""
    title, body = _new_grade_words(value, subject)
    event_id = _create_event(db, login, "grade", title, body,
                             subject=subject, lesson_id=lesson_id,
                             payload={"value": value} if value else {})
    return notify_login(
        db, login,
        title="Новая оценка",
        body="У вас новая оценка. Откройте журнал, чтобы посмотреть.",
        data={"type": "grade", "event_id": event_id},
    )


def notify_grade_changed(db, login: str, subject: str = "", lesson_id: str = "",
                         old: str = "", new: str = "") -> int:
    """Оценку ИСПРАВИЛИ. Отдельное событие, а не «новая оценка»: подмена одного другим
    дезинформирует — студент пойдёт искать несуществующий новый балл."""
    title, body = _changed_grade_words(old, new, subject)
    event_id = _create_event(db, login, "grade_changed", title, body,
                             subject=subject, lesson_id=lesson_id,
                             payload={"old": old, "new": new})
    return notify_login(
        db, login,
        title="Оценка изменена",
        body="Одну из ваших оценок изменили. Откройте журнал, чтобы посмотреть.",
        data={"type": "grade_changed", "event_id": event_id},
    )


def notify_schedule_changed(db, login: str, role: str = "student",
                            group: str = "") -> int:
    """Расписание изменилось. Рассылается ТОЛЬКО тем, кого это касается: студентам
    затронутой группы и ведущим у неё преподавателям (см. вызывающий код) — уведомлять
    весь колледж о правке одной ячейки значит приучить людей игнорировать уведомления."""
    title, body = _schedule_words(role, group)
    event_id = _create_event(db, login, "schedule_changed", title, body,
                             payload={"group": group})
    return notify_login(
        db, login,
        title="Расписание изменилось",
        body="В расписании есть изменения. Откройте приложение, чтобы посмотреть.",
        data={"type": "schedule_changed", "event_id": event_id},
    )


def notify_homework(db, login: str, subject: str = "", lesson_id: str = "",
                    task: str = "", number: int = 0,
                    author_login: str = "", batch_id: str = "") -> int:
    """Преподаватель задал домашнее задание. Уходит ВСЕМ студентам группы.

    В отличие от оценки, текст задания — не персональные данные: он одинаков для всей
    группы и не говорит ничего о конкретном человеке. Поэтому в письмо (которое хранится
    у нас) он попадает целиком — студенту важно видеть суть, не открывая журнал.

    А вот в САМ ПУШ задание всё равно не кладём: пуш идёт через серверы RuStore, и общее
    правило модуля — наружу отдаём только «есть новое» + id события. Заодно это защищает
    от неожиданности: преподаватель мог вписать в задание фамилии или ссылку на внутренний
    ресурс, и предугадать это на стороне отправки нельзя."""
    title, body = _homework_words(subject, task, number)
    event_id = _create_event(db, login, "homework", title, body,
                             subject=subject, lesson_id=lesson_id,
                             payload={"task": task, "number": number},
                             author_login=author_login, batch_id=batch_id)
    return notify_login(
        db, login,
        title="Новое домашнее задание",
        body="Вам задали домашнее задание. Откройте приложение, чтобы посмотреть.",
        data={"type": "homework", "event_id": event_id},
    )


def _homework_words(subject: str, task: str, number: int = 0) -> tuple:
    """(заголовок, тело) письма о ДЗ. Заголовок — с предметом, чтобы в списке уведомлений
    было понятно без открытия; тело — сам текст задания."""
    subj = (subject or "").strip()
    task = (task or "").strip()
    head = f"ДЗ по «{subj}»" if subj else "Домашнее задание"
    if not task:
        #Преподаватель мог не заполнить текст. Пустое письмо бессмысленно — зовём в журнал.
        return (head, "Преподаватель задал домашнее задание. Загляните в журнал.")
    return (head, f"Задание №{number}: {task}" if number else task)


def notify_reminder(db, login: str, text: str, conversation_id: str = "") -> int:
    """§D19: наступило напоминание, поставленное самим пользователем.

    Текст он написал (или выбрал) сам, так что в НАШЕМ письме он есть целиком. В пуш, как
    и везде, уходит только «есть напоминание» + id события: тело идёт через RuStore, а в
    сообщении переписки может оказаться что угодно."""
    snippet = (text or "").strip()
    body = snippet if len(snippet) <= 300 else snippet[:297] + "…"
    event_id = _create_event(db, login, "reminder", "Напоминание",
                             body or "Вы просили напомнить.",
                             payload={"conversation_id": conversation_id})
    return notify_login(
        db, login,
        title="Напоминание",
        body="Сработало напоминание. Откройте приложение, чтобы посмотреть.",
        data={"type": "reminder", "event_id": event_id,
              "conversation_id": conversation_id},
    )


def notify_event(db, login: str, title: str, body: str,
                 author_login: str = "", batch_id: str = "") -> int:
    """Мероприятие/событие (олимпиада, конкурс, выступление и т.п.) — заводит
    преподаватель или админ (см. `POST /web/events`), рассылается выбранной аудитории.
    Текст пишет автор — как и с ДЗ, это не персональные данные (одинаков для всех
    получателей), поэтому в НАШЕМ письме он целиком; в сам пуш — только факт события."""
    event_id = _create_event(db, login, "event", title, body,
                             author_login=author_login, batch_id=batch_id)
    return notify_login(
        db, login,
        title="Новое мероприятие",
        body="Появилось новое объявление о мероприятии. Откройте приложение, чтобы посмотреть.",
        data={"type": "event", "event_id": event_id},
    )


def prune_stale(db) -> int:
    """Убирает токены устройств, которые давно не подтверждались.

    Приложение подтверждает свой токен при каждом запуске. Молчит дольше TTL — значит
    его снесли или им не пользуются; держать такую запись значит бесконечно слать в
    пустоту и раздувать таблицу."""
    try:
        from .models import PushToken
        edge = (datetime.now(timezone.utc)
                - timedelta(days=config.PUSH_TOKEN_TTL_DAYS)).isoformat()
        stale = db.query(PushToken).filter(PushToken.last_seen < edge).all()
        for row in stale:
            db.delete(row)
        db.commit()
        return len(stale)
    except Exception as e:
        log.warning("уборка токенов не удалась: %s", e)
        db.rollback()
        return 0
