"""
retention.py — Политика хранения: что и когда физически удаляется из боевой базы.

Зачем это вообще есть. Две причины, и обе не про экономию места:

  1. **152-ФЗ**: персональные данные хранятся не дольше, чем этого требует цель
     обработки. «Храним всё и навсегда» — не позиция, а нарушение, и первый же вопрос
     проверяющего будет именно об этом.
  2. **Размер утечки**. Крупнейшая авария в нашей нише (PowerSchool, 62 млн записей)
     оказалась такой крупной ровно потому, что у поставщика лежали «десятилетия
     хранимых записей». Удалённые данные украсть нельзя.

🔑 ГЛАВНАЯ ОПАСНОСТЬ, ради которой окна такие длинные. Удаление у нас идёт НАДГРОБИЯМИ
(строка остаётся с `deleted=True`), потому что дельта-pull приносит изменения, а не
отсутствия: пропавшую строку клиент просто не заметит. Значит физическое удаление
надгробия — это удаление ЕДИНСТВЕННОГО свидетельства о том, что запись убрали. ПК,
который не синхронизировался с момента удаления и до уборки надгробия, при следующем
push вернёт строку живой — воскрешение данных, которые админ удалил намеренно.

Отсюда правило: окно уборки надгробий обязано быть заведомо больше любого правдоподобного
срока офлайна преподавательского ПК. Полгода — это каникулы плюс отпуск плюс запас.
Второй рубеж — сверка «сервер = истина» (`sync_engine.reconcile`), которая при каждом
входе стирает локальный кэш и наливает его заново: машина, пролежавшая полгода,
приводится к серверу ДО того, как что-то отправит.

⚠️ ЖУРНАЛ БЕЗОПАСНОСТИ (`audit_events`) НЕ УБИРАЕТСЯ ЗДЕСЬ СОВСЕМ. Его докстринг прямо
обещает «записи НЕ редактируются и НЕ удаляются приложением», и это не небрежность: он
доказательная база при разборе инцидента, а инцидент обнаруживается позже, чем
происходит. Срок его хранения — вопрос регламента учреждения и ручной выгрузки, а не
фонового кода, который однажды сотрёт ровно то, что понадобится.

Как запускается. Планировщика нет — на одноядерном VPS вечный фоновый поток стоит
дороже, чем проверка одной метки. Тот же приём, что у напоминаний (`_fire_due_reminders`)
и просроченных жалоб (`_expire_stale_reports`): попутно с запросом, который и так
происходит, но не чаще раза в сутки на процесс. Каждый прогон ограничен сверху по числу
строк — первая уборка на большой базе не имеет права держать чей-то HTTP-запрос.
"""
import os
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import SYNC_MODELS

#Сколько живёт НАДГРОБИЕ, прежде чем строку можно удалить физически. Полгода — см.
#разбор опасности в шапке модуля. Уменьшать без понимания последствий нельзя: цена
#ошибки — воскресшие данные у того ПК, который дольше всех был офлайн.
TOMBSTONE_DAYS = int(os.environ.get("GRADEBOOK_TOMBSTONE_DAYS", "180"))

#Записи о выданных сессиях. Живая сессия — 5 часов (неделя у телефона), дальше строка
#нужна только как история для админского раздела «Сессии и доступ». Одна строка на
#каждый вход: двести человек по два входа в день дают ~146 000 строк в год.
AUTH_SESSION_DAYS = int(os.environ.get("GRADEBOOK_SESSION_KEEP_DAYS", "90"))

#Уведомления. Прочитанные — история на три месяца; непрочитанные держим дольше (человек
#мог болеть), но тоже не вечно: в теле письма лежат предмет и балл, то есть ПДн.
NOTIFY_READ_DAYS = int(os.environ.get("GRADEBOOK_NOTIFY_READ_DAYS", "90"))
NOTIFY_ANY_DAYS = int(os.environ.get("GRADEBOOK_NOTIFY_KEEP_DAYS", "365"))

#Сработавшие напоминания. ⚠️ Отдельный и неочевидный пункт: `Reminder.text` — это СНИМОК
#текста сообщения, сделанный намеренно (автор может сообщение отредактировать). Побочно
#это значит, что копия переживает УДАЛЕНИЕ исходного сообщения: человек стёр переписку, а
#строка с её текстом осталась. Утечкой наружу это не является (та же зашифрованная база),
#но хранением дольше цели — является.
REMINDER_DAYS = int(os.environ.get("GRADEBOOK_REMINDER_KEEP_DAYS", "90"))

#История правок сообщений. Нужна модерации: автор мог исправить текст после жалобы. Но
#жалоба живёт часы (тикет сам истекает через 10), а текст ДО правки лежал вечно.
MESSAGE_EDIT_DAYS = int(os.environ.get("GRADEBOOK_MSG_EDIT_KEEP_DAYS", "180"))

#Тело УДАЛЁННОГО сообщения. Строка-надгробие остаётся навсегда (иначе из переписки
#пропадёт отметка «сообщение удалено» и поедут ответы на него), а вот сам текст через
#полгода гасим: он восстанавливается только для модерации, а модерации он через полгода
#уже не нужен.
DELETED_BODY_DAYS = int(os.environ.get("GRADEBOOK_DELETED_BODY_KEEP_DAYS", "180"))

#След срабатывания пасхалки. Нужен ровно для суточного кулдауна, дальше это балласт:
#строка на каждое срабатывание у каждого человека, и растёт она монотонно. Полгода —
#с большим запасом; сам кулдаун живёт сутки.
EGG_LOG_DAYS = int(os.environ.get("GRADEBOOK_EGG_LOG_KEEP_DAYS", "180"))

#Потолок строк на одну таблицу за прогон. Первая уборка на базе, копившейся годами, иначе
#удалила бы десятки тысяч строк внутри чужого HTTP-запроса. Остаток уедет следующим днём.
MAX_ROWS_PER_TABLE = int(os.environ.get("GRADEBOOK_RETENTION_BATCH", "5000"))

#Не чаще раза в сутки на процесс.
EVERY_HOURS = int(os.environ.get("GRADEBOOK_RETENTION_EVERY_H", "24"))

_lock = threading.Lock()
_last_run: datetime | None = None


def _cutoff(days: int) -> str:
    """Граница «старше чего» в том же ISO-формате со смещением, в каком мы пишем все
    метки. Формат обязан совпадать: сравнение идёт СТРОКОВОЕ (как и в /sync/pull), и
    работает оно ровно потому, что обе стороны печатает одна функция."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _delete_capped(db: Session, model, *conditions) -> int:
    """Удалить не больше MAX_ROWS_PER_TABLE строк, подходящих под условия.

    Через выборку первичных ключей, а не `query(...).delete()`: последний в SQLAlchemy
    не умеет LIMIT на SQLite, а без потолка первая уборка заблокировала бы таблицу на
    неопределённое время."""
    pks = list(model.__table__.primary_key.columns)
    if len(pks) != 1:
        #⚠️ Заслонка на будущее. Сегодня составных ключей нет ни у одной таблицы, но
        #появись он — выборка по ПЕРВОЙ колонке ключа совпала бы с ЧУЖИМИ строками, и
        #уборка удалила бы не то. Молча брать `[0]` здесь нельзя: цена ошибки — потеря
        #данных, а заметили бы её через полгода. Лучше громкий отказ одной уборки.
        raise RuntimeError(
            f"у таблицы «{model.__tablename__}» составной первичный ключ — уборка по "
            f"одной колонке удалила бы чужие строки; нужен явный разбор этого случая")
    pk = pks[0]
    rows = (db.query(pk).filter(*conditions).limit(MAX_ROWS_PER_TABLE).all())
    keys = [r[0] for r in rows]
    if not keys:
        return 0
    (db.query(model).filter(pk.in_(keys))
       .delete(synchronize_session=False))
    return len(keys)


def purge_tombstones(db: Session, days: int = TOMBSTONE_DAYS) -> dict:
    """Физически удалить надгробия старше `days` во всех синхронизируемых таблицах.

    Возвращает {таблица: сколько удалено} — только непустые, чтобы обычный прогон не
    писал в лог одиннадцать нулей."""
    cutoff = _cutoff(days)
    out: dict[str, int] = {}
    for name, model in SYNC_MODELS.items():
        n = _delete_capped(db, model,
                           model.deleted == True,          # noqa: E712
                           model.updated_at != "",
                           model.updated_at < cutoff)
        if n:
            out[name] = n
    return out


def purge_sessions(db: Session, days: int = AUTH_SESSION_DAYS) -> int:
    """Старые записи о выданных токенах. Убираем ПО ДАТЕ ВЫДАЧИ, а не по `revoked`:
    отозванная вчера сессия ещё интересна админу, а невостребованная годичной давности —
    уже нет, независимо от флага."""
    from .models import AuthSession
    return _delete_capped(db, AuthSession,
                          AuthSession.issued_at != "",
                          AuthSession.issued_at < _cutoff(days))


def purge_notifications(db: Session, read_days: int = NOTIFY_READ_DAYS,
                        any_days: int = NOTIFY_ANY_DAYS) -> int:
    """Уведомления: прочитанные — быстрее, непрочитанные — дольше, но не вечно."""
    from .models import NotifyEvent
    n = _delete_capped(db, NotifyEvent,
                       NotifyEvent.read_at != "",
                       NotifyEvent.created_at != "",
                       NotifyEvent.created_at < _cutoff(read_days))
    n += _delete_capped(db, NotifyEvent,
                        NotifyEvent.created_at != "",
                        NotifyEvent.created_at < _cutoff(any_days))
    return n


def purge_reminders(db: Session, days: int = REMINDER_DAYS) -> int:
    """Только СРАБОТАВШИЕ напоминания (`fired_at` заполнен). Несработавшее — это
    обещание человеку, и его нельзя убрать по сроку давности: напоминание вполне может
    быть поставлено на следующий семестр."""
    from .models import Reminder
    return _delete_capped(db, Reminder,
                          Reminder.fired_at != "",
                          Reminder.fired_at < _cutoff(days))


def purge_message_edits(db: Session, days: int = MESSAGE_EDIT_DAYS) -> int:
    """История правок сообщений старше срока."""
    from .models import MessageEdit
    return _delete_capped(db, MessageEdit,
                          MessageEdit.edited_at != "",
                          MessageEdit.edited_at < _cutoff(days))


def purge_egg_log(db: Session, days: int = EGG_LOG_DAYS) -> int:
    """След срабатывания пасхалок старше срока.

    ⚠️ Ачивки (`user_achievements`) НЕ трогаем НИКОГДА и здесь их нет намеренно: это
    то, что человек нашёл сам, и срока давности у находки не бывает. Убирается только
    лог срабатываний, по которому считается суточный кулдаун."""
    from .models import EasterEggLog
    return _delete_capped(db, EasterEggLog,
                          EasterEggLog.triggered_at != "",
                          EasterEggLog.triggered_at < _cutoff(days))


def blank_deleted_bodies(db: Session, days: int = DELETED_BODY_DAYS) -> int:
    """Погасить ТЕКСТ давно удалённых сообщений, оставив саму строку-надгробие.

    Строку не трогаем намеренно: на неё ссылаются ответы (`reply_to_id`) и по ней в ленте
    рисуется «сообщение удалено». Пропадёт строка — ответы повиснут в пустоту, и это
    увидят все участники беседы. Пропадёт текст — не увидит никто, кроме модерации,
    которой он через полгода уже не нужен."""
    from .models import Message
    cutoff = _cutoff(days)
    rows = (db.query(Message)
            .filter(Message.deleted_at != "",
                    Message.deleted_at < cutoff,
                    Message.body != "")
            .limit(MAX_ROWS_PER_TABLE).all())
    for m in rows:
        m.body = ""
    return len(rows)


def run_all(db: Session) -> dict:
    """Один полный проход политики хранения. Ничего не бросает наружу.

    ⚠️ Отдельный `commit` на каждый шаг — НЕ избыточность. Прогон делает несколько
    независимых уборок, и падение пятой не имеет права откатывать первые четыре: они
    удаляют РАЗНЫЕ данные по РАЗНЫМ основаниям, между ними нет транзакционной связи."""
    report: dict = {}
    steps = (
        ("tombstones", lambda: purge_tombstones(db)),
        ("sessions", lambda: purge_sessions(db)),
        ("notifications", lambda: purge_notifications(db)),
        ("reminders", lambda: purge_reminders(db)),
        ("message_edits", lambda: purge_message_edits(db)),
        ("egg_log", lambda: purge_egg_log(db)),
        ("deleted_bodies", lambda: blank_deleted_bodies(db)),
    )
    for name, fn in steps:
        try:
            res = fn()
            db.commit()
            if res:
                report[name] = res
        except Exception as e:      # noqa: BLE001
            db.rollback()
            #Сбой одной уборки не должен ни ронять запрос, ни отменять остальные, но и
            #исчезать бесследно не имеет права: политика хранения — это то, о чём
            #спросят при проверке, и «она вроде работала» не ответ.
            report[name] = f"ошибка: {e}"
            print(f"[retention] шаг «{name}» не выполнен: {e}")
    return report


def maybe_run(db: Session) -> dict | None:
    """Запустить уборку, если с прошлого раза прошли сутки. Иначе — сразу выйти.

    Зовётся с горячего пути (`GET /me/events`), поэтому проверка обязана быть дешёвой:
    сравнение метки в памяти, без единого запроса к базе."""
    global _last_run
    now = datetime.now(timezone.utc)
    with _lock:
        if _last_run is not None and (now - _last_run) < timedelta(hours=EVERY_HOURS):
            return None
        #Метку ставим ДО работы: если прогон упадёт, второй попытки в ту же минуту с
        #соседнего запроса быть не должно — она упадёт так же, только шумнее.
        _last_run = now
    report = run_all(db)
    if report:
        print(f"[retention] политика хранения применена: {report}")
    return report
