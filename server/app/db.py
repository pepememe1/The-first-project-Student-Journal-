"""
db.py — Подключение к базе (SQLAlchemy).

Один и тот же код работает и с SQLite (разработка), и с PostgreSQL (боевой
сервер ВСГУТУ) — отличается только строка подключения GRADEBOOK_DB_URL.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

from .config import DATABASE_URL, DB_KEY

_IS_SQLITE = DATABASE_URL.startswith("sqlite")
#Для SQLite нужен check_same_thread=False (FastAPI работает в нескольких потоках).
_connect_args = {"check_same_thread": False} if _IS_SQLITE else {}


def _build_engine():
    """Движок БД. Если задан GRADEBOOK_DB_KEY и доступен драйвер sqlcipher3 — поднимаем
    движок поверх SQLCipher: файл БД шифруется ЦЕЛИКОМ (AES-256), ПДн at rest (152-ФЗ).
    Ключ (64 hex, raw 256-bit) задаётся PRAGMA key ПЕРВОЙ операцией КАЖДОГО соединения.
    Нет ключа/драйвера (напр. Windows-dev, CI без ключа) → обычный SQLite: схема id и
    тесты не меняются. Ключ БД нигде не логируем."""
    if _IS_SQLITE and DB_KEY:
        try:
            import sqlcipher3
        except ImportError:
            print("[db] GRADEBOOK_DB_KEY задан, но драйвер sqlcipher3 не установлен "
                  "(на Windows-dev это нормально) — БД работает БЕЗ шифрования файла.")
        else:
            path = DATABASE_URL.split("sqlite:///", 1)[-1]

            def _creator():
                conn = sqlcipher3.connect(path, check_same_thread=False)
                conn.execute("PRAGMA key = \"x'%s'\"" % DB_KEY)   # ДО любых других операций
                return conn

            print("[db] Файл БД шифруется (SQLCipher, AES-256).")
            #poolclass=QueuePool — ОБЯЗАТЕЛЬНО, не убирать.
            #Файл БД мы открываем через creator, поэтому URL здесь пустой («sqlite://»).
            #Но для такого URL SQLAlchemy считает базу IN-MEMORY и молча берёт
            #SingletonThreadPool — пул «одно соединение на поток», предназначенный для
            #тестов с памятью. Он ЗАКРЫВАЕТ лишние соединения сверх size, а FastAPI
            #обслуживает синхронные эндпоинты из пула потоков → соединение закрывалось
            #под работающей сессией, и SQLAlchemy падал на откате:
            #   sqlcipher3.dbapi2.ProgrammingError: Cannot operate on a closed database
            #(ловили на бою при живых пользователях). QueuePool — нормальный пул с
            #переиспользованием: соединения не закрываются произвольно, а PRAGMA key
            #(тяжёлый KDF) выполняется только при создании нового соединения, а не на
            #каждый запрос. Потокобезопасно: creator ставит check_same_thread=False.
            return create_engine("sqlite://", creator=_creator, pool_pre_ping=True,
                                 poolclass=QueuePool)
    return create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)


engine = _build_engine()


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):
        """Настраиваем КАЖДОЕ SQLite-соединение под конкурентную нагрузку.

        Зачем: под утренним «гердом» входов колледжа несколько запросов пишут в БД
        одновременно (вход теперь ещё и создаёт строки сессии — auth_sessions). Без
        этих PRAGMA SQLite сериализует запись и при конфликте СРАЗУ падает «database is
        locked». С WAL читатели не блокируют писателя, а busy_timeout заставляет
        писателей ЖДАТЬ освобождения блокировки, а не падать. (Как в десктопном core.py.)
        Для настоящего масштаба всё равно PostgreSQL — но SQLite так держится дольше."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")     #параллельные читатели + один писатель
        cur.execute("PRAGMA busy_timeout=5000")    #ждать блокировку до 5 c, а не падать
        cur.execute("PRAGMA synchronous=NORMAL")   #безопасно и быстрее при WAL
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Зависимость FastAPI: открыть сессию на запрос и гарантированно закрыть."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Создаёт таблицы, если их нет. Вызывается при старте приложения."""
    from . import models  #noqa: F401 — регистрируем модели в метаданных
    Base.metadata.create_all(bind=engine)
    _ensure_user_prefs_column()
    _ensure_user_patronymic_column()
    _backfill_patronymic()
    _ensure_lesson_term_columns()
    _backfill_lesson_term()
    _ensure_user_curated_groups_column()
    _ensure_grade_student_id_columns()
    _ensure_notify_event_columns()
    _ensure_participant_state_columns()


def _ensure_user_prefs_column():
    """Идемпотентная мини-миграция: добавляет столбец users.prefs на УЖЕ
    существующей базе. create_all создаёт только отсутствующие ТАБЛИЦЫ, новые
    столбцы он не досоздаёт — поэтому на старой базе колледжа prefs надо добавить
    ALTER-ом. На свежей БД столбец уже создан через create_all, и мы просто выходим."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        return  #таблицы ещё нет — её только что создал create_all со столбцом
    if "prefs" in columns:
        return
    #Тип столбца для JSON: в SQLite это TEXT, в PostgreSQL — JSON/JSONB. Берём
    #нейтральный JSON — SQLAlchemy/драйвер отобразит его в подходящий тип СУБД.
    is_pg = engine.url.get_backend_name().startswith("postgres")
    coltype = "JSONB" if is_pg else "JSON"
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE users ADD COLUMN prefs {coltype}"))


def _ensure_user_patronymic_column():
    """Идемпотентная мини-миграция: добавляет столбец users.patronymic (отчество
    отдельным полем) на уже существующей базе. На свежей БД он создан create_all."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        return
    if "patronymic" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN patronymic VARCHAR DEFAULT ''"))


def _backfill_patronymic():
    """Разово заполняет patronymic из уже существующих ФИО: отчество исторически
    хранилось внутри name («Имя Отчество»). Берём хвост после ПЕРВОГО пробела.

    ВАЖНО: name НЕ меняем (он — ключ оценок/синка). Трогаем только строки, где
    patronymic ещё пуст, а в name есть пробел — идемпотентно и безопасно к повтору.
    Заполненное вручную отчество не перетираем."""
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT id, name FROM users WHERE role='student' "
                "AND (patronymic IS NULL OR patronymic='') "
                "AND name LIKE '% %'")).fetchall()
            for uid, name in rows:
                patr = (name or "").split(" ", 1)[1].strip() if " " in (name or "") else ""
                if patr:
                    conn.execute(text("UPDATE users SET patronymic=:p WHERE id=:i"),
                                 {"p": patr, "i": uid})
    except Exception as e:
        print(f"[db] backfill patronymic пропущен: {e}")


def default_term() -> tuple:
    """Текущий учебный термин по дате сервера: (год «YYYY/YYYY+1», семестр 1|2).

    Календарь:
      • сен–дек  → осень (сем1) наступившего года Y/Y+1;
      • янв      → осень (сем1) продолжается, год Y-1/Y;
      • фев–июнь → весна (сем2), год Y-1/Y;
      • ИЮЛЬ–АВГ → летний перерыв. Считаем НАСТУПАЮЩУЮ осень Y/Y+1 (сем1).

    Про июль–август отдельно. Раньше они относились к ПРОШЕДШЕЙ весне (Y-1/Y сем2), и в
    июле «текущим» оказывался семестр уже завершённого учебного года — а преподаватель
    летом готовит сентябрь, а не смотрит назад. Из-за этого занятия, заведённые на новый
    учебный год, попадали в «будущий» термин и не показывались в журнале по умолчанию.
    Теперь лето плавно перетекает в осень: июль→сентябрь дают ОДИН и тот же термин, скачка
    нет. Единый источник дефолта для миграции и конфига (webdata/desktop дублируют —
    формула обязана совпадать до символа, иначе ключи term_grades разъедутся)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    if m >= 9:
        return f"{y}/{y + 1}", 1
    if m == 1:
        return f"{y - 1}/{y}", 1
    if m <= 6:
        return f"{y - 1}/{y}", 2
    return f"{y}/{y + 1}", 1        #июль–август: наступающая осень


def _ensure_participant_state_columns():
    """Идемпотентная мини-миграция: столбцы conversation_participants.muted / .pinned
    (мьют беседы и закрепление чата у пользователя). На свежей БД их создаёт create_all;
    на базе, где таблица участников появилась раньше этих полей, добавляем ALTER-ом —
    иначе запрос/запись p.muted упали бы. Таблицы может не быть (мессенджер не
    инициализирован) — тогда просто выходим."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("conversation_participants")}
    except Exception:
        return  #таблицы ещё нет — create_all создаст её со всеми столбцами
    with engine.begin() as conn:
        if "muted" not in columns:
            conn.execute(text(
                "ALTER TABLE conversation_participants ADD COLUMN muted BOOLEAN DEFAULT 0"))
        if "pinned" not in columns:
            conn.execute(text(
                "ALTER TABLE conversation_participants ADD COLUMN pinned BOOLEAN DEFAULT 0"))
        #«Удалить переписку у себя»: граница видимости истории и скрытие чата из списка.
        if "cleared_at" not in columns:
            conn.execute(text(
                "ALTER TABLE conversation_participants ADD COLUMN cleared_at VARCHAR DEFAULT ''"))
        if "hidden" not in columns:
            conn.execute(text(
                "ALTER TABLE conversation_participants ADD COLUMN hidden BOOLEAN DEFAULT 0"))


def _ensure_grade_student_id_columns():
    """Идемпотентная мини-миграция: grades.student_id / term_grades.student_id.

    ЭТАП 1 перехода с ФИО-ключей на неизменяемый id студента. Столбец ДОБАВОЧНЫЙ:
    первичный ключ остаётся прежним (f|n|lesson_id), поэтому старые клиенты, которые о
    поле не знают, продолжают работать — они просто шлют записи без него.

    Зачем вообще: оценка ключуется по написанию ФИО. Студентка выходит замуж, админ
    правит фамилию — и вся история оценок остаётся висеть на старом ключе. id строки
    users не меняется никогда, поэтому привязка к нему такой проблемы не имеет.
    """
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in ("grades", "term_grades"):
            try:
                columns = {c["name"] for c in insp.get_columns(table)}
            except Exception:
                continue        #таблицы ещё нет — create_all создал её уже со столбцом
            if "student_id" not in columns:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN student_id VARCHAR DEFAULT ''"))


def _ensure_lesson_term_columns():
    """Идемпотентная мини-миграция: столбцы lessons.year / lessons.semester (учебный
    период). На свежей БД создаются через create_all, на существующей — ALTER-ом."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("lessons")}
    except Exception:
        return
    with engine.begin() as conn:
        if "year" not in columns:
            conn.execute(text("ALTER TABLE lessons ADD COLUMN year VARCHAR DEFAULT ''"))
        if "semester" not in columns:
            conn.execute(text("ALTER TABLE lessons ADD COLUMN semester INTEGER DEFAULT 0"))


def _backfill_lesson_term():
    """Разово проставляет период занятиям, у которых он ещё не задан (историческим).
    Ставим ТЕКУЩИЙ термин по дате — чтобы старые занятия попали в актуальный период и
    не «выпали» из фильтра. Идемпотентно: трогаем только year='' / NULL."""
    from sqlalchemy import text
    try:
        y, s = default_term()
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE lessons SET year=:y, semester=:s "
                "WHERE (year IS NULL OR year='') "), {"y": y, "s": s})
            #у части могло проставиться year, но semester=0 — добьём семестр
            conn.execute(text(
                "UPDATE lessons SET semester=:s WHERE (semester IS NULL OR semester=0)"),
                {"s": s})
    except Exception as e:
        print(f"[db] backfill lesson term пропущен: {e}")


def _ensure_user_curated_groups_column():
    """Идемпотентная мини-миграция: users.curated_groups (JSON-список групп, которые
    курирует преподаватель). Непустой список = роль куратора (role остаётся teacher)."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("users")}
    except Exception:
        return
    if "curated_groups" in columns:
        return
    is_pg = engine.url.get_backend_name().startswith("postgres")
    coltype = "JSONB" if is_pg else "JSON"
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE users ADD COLUMN curated_groups {coltype}"))


def _ensure_notify_event_columns():
    """Идемпотентная мини-миграция: notify_events.title/body/payload — готовый текст
    уведомления для вкладки «Уведомления».

    Таблица уже существует на проде (приехала вместе с пушами об оценках), а create_all
    новые СТОЛБЦЫ не досоздаёт — поэтому ALTER. Уже накопленные события останутся с
    пустым текстом, и это нормально: клиент умеет показать их по kind, как и раньше.
    Задним числом сочинять им тело мы не имеем права — человек получал другое."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        columns = {c["name"] for c in insp.get_columns("notify_events")}
    except Exception:
        return          #таблицы ещё нет — create_all создал её сразу со столбцами
    is_pg = engine.url.get_backend_name().startswith("postgres")
    #Столбцы добавляем по одному: часть могла появиться в прошлый запуск, а СУБД
    #откажет на попытке добавить уже существующий.
    wanted = (("title", "VARCHAR DEFAULT ''"),
              ("body", "VARCHAR DEFAULT ''"),
              ("payload", "JSONB" if is_pg else "JSON"))
    with engine.begin() as conn:
        for name, coltype in wanted:
            if name not in columns:
                conn.execute(text(
                    f"ALTER TABLE notify_events ADD COLUMN {name} {coltype}"))
