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


def notify_login(db, login: str, title: str, body: str, data: dict | None = None) -> int:
    """Разослать на ВСЕ устройства пользователя. Возвращает число успешных отправок.

    Не бросает исключений ВООБЩЕ, и это проверяется тестом: функция вызывается из
    обработчика выставления оценки, и сбой доставки не должен мешать преподавателю
    поставить балл. Раньше обещание было только в докстринге — исключение из
    send_to_token проходило наружу и роняло запрос."""
    if not config.push_enabled():
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


def notify_new_grade(db, login: str, subject: str = "", lesson_id: str = "") -> int:
    """Уведомление студенту о новой оценке + событие для перехода в нужный журнал.

    Текст намеренно БЕЗ балла, предмета и ФИО: он идёт через посредника (см. шапку
    модуля). В пуш уезжает только id события; предмет и занятие приложение получит от
    НАС, открывшись. Побочный выигрыш: если токен входа сгорел, приложение запомнит id,
    покажет вход и совершит переход после него — событие не потеряется."""
    import uuid
    from .models import NotifyEvent
    event_id = str(uuid.uuid4())
    try:
        db.add(NotifyEvent(id=event_id, login=login, kind="grade",
                           subject=subject or "", lesson_id=lesson_id or "",
                           created_at=_now_iso()))
        db.commit()
    except Exception as e:
        log.warning("не удалось сохранить событие уведомления: %s", e)
        db.rollback()
        event_id = ""        #пуш всё равно отправим, просто без адресного перехода
    return notify_login(
        db, login,
        title="Новая оценка",
        body="У вас новая оценка. Откройте журнал, чтобы посмотреть.",
        data={"type": "grade", "event_id": event_id},
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
