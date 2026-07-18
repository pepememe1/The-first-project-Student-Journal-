"""
models.py — Таблицы БД (SQLAlchemy).

Каждая синхронизируемая сущность несёт служебные поля для offline-first синка:
  • updated_at — ISO-метка последнего изменения (строка, лексикографически
    сортируется как время). По ней работает дельта-синк и разрешение конфликтов
    «последний по времени побеждает».
  • deleted — «надгробие» (tombstone): удаление не стирает строку, а помечает её,
    чтобы удаление доехало до всех ПК (иначе на других ПК запись «воскресала» бы).
"""
from sqlalchemy import Column, Integer, String, Boolean, JSON

from .db import Base


class User(Base):
    """Пользователь: администратор / преподаватель / студент."""
    __tablename__ = "users"
    id = Column(String, primary_key=True)              #uuid
    role = Column(String, nullable=False)              #admin | teacher | student
    login = Column(String, index=True, default="")
    password_hash = Column(String, default="")
    full_name = Column(String, default="")             #ФИО (у преподавателя — ключ)
    surname = Column(String, default="")
    #ВАЖНО: name хранит «Имя Отчество» (полную форму) и служит КЛЮЧОМ оценок
    #(grades.student_n = name) и ключом студента при синке (stud:surname|name|group).
    #Менять его формат нельзя — иначе осиротеют оценки и рассинхронится десктоп.
    name = Column(String, default="")
    #Отчество ОТДЕЛЬНЫМ полем (для раздельного показа/ввода). Дублирует хвост name,
    #но name остаётся неизменным ключом. first_name для показа = name без patronymic.
    patronymic = Column(String, default="")
    group_name = Column(String, default="")            #для студента
    subjects = Column(JSON, default=list)              #для преподавателя
    group_assignments = Column(JSON, default=dict)     #для преподавателя
    #Группы, которые преподаватель КУРИРУЕТ (роль куратора). Непустой список = куратор;
    #отдельная роль не заводится (role остаётся teacher). Куратор ВИДИТ все предметы своих
    #групп (в т.ч. чужие) в режиме ТОЛЬКО ЧТЕНИЕ — см. routers/web.py /web/curator/*.
    curated_groups = Column(JSON, default=list)
    #Личные настройки пользователя (тема оформления и пр.). Меняет ТОЛЬКО сам
    #пользователь через self-эндпоинт POST /me/prefs (роли/пароль не затрагиваются).
    #Уезжает клиентам обычным pull (как и прочие столбцы) — так тема «роумится».
    prefs = Column(JSON, default=dict)
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class Group(Base):
    __tablename__ = "groups"
    id = Column(String, primary_key=True)
    name = Column(String, index=True, default="")
    subjects = Column(JSON, default=list)
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class Subject(Base):
    __tablename__ = "subjects"
    id = Column(String, primary_key=True)
    name = Column(String, index=True, default="")
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class Lesson(Base):
    __tablename__ = "lessons"
    id = Column(String, primary_key=True)              #uuid (как в десктопе)
    group_name = Column(String, index=True, default="")
    subject = Column(String, index=True, default="")
    type = Column(String, default="")
    number = Column(Integer, default=0)
    topic = Column(String, default="")
    date = Column(String, default="")
    retake_date = Column(String, default="")
    hour = Column(Integer, default=0)
    #Измерение УЧЕБНОГО ПЕРИОДА (фундамент долгосрочного журнала): год «2025/2026» и
    #семестр (1..8). Оценки наследуют период от занятия (ключ оценки не трогаем). Новые
    #занятия штампуются ТЕКУЩИМ термином из config; старые бэкфилл-ятся при миграции.
    year = Column(String, index=True, default="")
    semester = Column(Integer, index=True, default=0)
    extra = Column(JSON, default=dict)                 #retake_date_2..5 и пр.
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class Grade(Base):
    __tablename__ = "grades"
    id = Column(String, primary_key=True)              #f|n|lesson_id
    student_f = Column(String, index=True, default="")
    student_n = Column(String, index=True, default="")
    lesson_id = Column(String, index=True, default="")
    grade = Column(String, default="")
    device = Column(String, default="")                #имя ПК — для конфликтов
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class TermGrade(Base):
    """Итоговая оценка за семестр по предмету (промежуточная аттестация) — отдельно от
    Grade (та — по конкретным занятиям). Ключ: студент+предмет+год+семестр. Из неё
    строятся ведомости. Входит в SYNC_MODELS: десктоп ведёт аттестацию/ведомости
    наравне с вебом, данные общие (десктопная таблица term_grades ↔ эта)."""
    __tablename__ = "term_grades"
    id = Column(String, primary_key=True)              #f|n|subject|year|semester
    student_f = Column(String, index=True, default="")
    student_n = Column(String, index=True, default="")
    subject = Column(String, index=True, default="")
    year = Column(String, index=True, default="")
    semester = Column(Integer, index=True, default=0)
    grade = Column(String, default="")                 #5/4/3/2 | Зачтено/Не зачтено
    form = Column(String, default="")                  #зачёт | экзамен | диффзачёт
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class ConfigKV(Base):
    """Глобальные настройки (ключ → JSON): API-ключи, методика оценок и т.п."""
    __tablename__ = "config"
    key = Column(String, primary_key=True)
    value = Column(JSON)
    updated_at = Column(String, default="", index=True)
    deleted = Column(Boolean, default=False)


class ApprovedDevice(Base):
    """Устройство (ПК), которому администратор разрешил подключаться к серверу.

    Барьер подтверждения: пока device_id не лежит здесь, сервер отвергает вход и
    синхронизацию с этого устройства (см. connect.device_allowed). В отличие от
    «ожидающих» запросов (они транзиентны, живут в памяти — connect.py), одобренные
    устройства ДОЛЖНЫ переживать перезапуск сервера, поэтому хранятся в БД.

    Намеренно НЕ входит в SYNC_MODELS: это серверная деталь доступа, клиентам её
    синхронизировать незачем."""
    __tablename__ = "approved_devices"
    device_id = Column(String, primary_key=True)       #uuid с клиента (X-Device-Id)
    ip = Column(String, default="")                    #IP на момент одобрения
    hostname = Column(String, default="")              #имя ПК (для опознания админом)
    approved_at = Column(String, default="")           #ISO-метка одобрения (UTC)
    approved_by = Column(String, default="")           #логин админа, одобрившего


class AuthSession(Base):
    """Выданный токен (сессия). Нужен для трёх вещей сразу:

      • ЧЁРНЫЙ СПИСОК / отзыв: пока запись не `revoked`, токен с этим `jti` валиден;
        админ (или logout) ставит `revoked=True` — и сервер мгновенно перестаёт пускать
        этот токен, даже если по подписи и `exp` он ещё «живой» (важно для 152-ФЗ:
        экстренная блокировка, безопасный выход, смена ролей на лету);
      • REFRESH: долгоживущий refresh-токен (kind='refresh') обменивается на новый
        access через /auth/refresh — клиент не выкидывает пользователя на логин, когда
        короткий access протух посреди работы;
      • ВИДИМОСТЬ: админ видит список активных сессий (кто, с какого устройства, до когда).

    Серверная деталь доступа — НЕ входит в SYNC_MODELS (клиентам синхронизировать незачем)."""
    __tablename__ = "auth_sessions"
    jti = Column(String, primary_key=True)             #уникальный id токена (из payload)
    login = Column(String, index=True, default="")
    role = Column(String, default="")
    kind = Column(String, default="access")            #access | refresh
    device_id = Column(String, default="")             #X-Device-Id, с которого выдан
    ip = Column(String, default="")
    issued_at = Column(String, default="")             #ISO UTC
    expires_at = Column(Integer, default=0, index=True)  #unix ts (быстрый фильтр/чистка)
    revoked = Column(Boolean, default=False)
    pair_jti = Column(String, default="")              #связанный токен (access↔refresh)


class RegistrationRequest(Base):
    """Заявка студента на самостоятельную регистрацию с экрана входа. Ждёт одобрения
    администратора: тот подтверждает → система генерирует логин(=email)+пароль, заводит
    студента и шлёт креды на почту. Серверная деталь доступа — НЕ входит в SYNC_MODELS
    (заявки клиентам синхронизировать незачем)."""
    __tablename__ = "registration_requests"
    id = Column(String, primary_key=True)              #uuid
    full_name = Column(String, default="")
    group_name = Column(String, default="")            #РАЗРЕШЁННАЯ группа (после resolve)
    phone = Column(String, default="")
    email = Column(String, index=True, default="")     #станет логином
    status = Column(String, default="pending")         #pending | approved | rejected
    created_at = Column(String, default="")
    note = Column(String, default="")                  #причина отклонения и т.п.


class AuditEvent(Base):
    """Журнал значимых действий (ФСТЭК №21, п. регистрации событий безопасности).

    В отличие от `events.py` (кольцевой буфер В ПАМЯТИ, живёт до перезапуска) — это
    ПЕРСИСТЕНТНЫЙ, только-на-добавление журнал в БД: входы/выходы, выдача и отзыв
    доступа, изменения оценок и ПДн, одобрение/отклонение регистраций. Нужен для
    разбора инцидентов и как доказательная база при проверке. Записи НЕ редактируются
    и НЕ удаляются приложением. Серверная деталь — НЕ входит в SYNC_MODELS."""
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_ts = Column(Integer, default=0, index=True)   #unix ts — быстрый фильтр/сортировка
    ts = Column(String, default="")                       #ISO UTC — человекочитаемо
    actor = Column(String, index=True, default="")        #логин инициатора ("" = аноним/система)
    role = Column(String, default="")
    ip = Column(String, default="")
    device = Column(String, default="")                   #X-Device-Id (усечённо)
    action = Column(String, index=True, default="")       #короткий код: login.ok, grade.set…
    target = Column(String, default="")                   #на кого/что подействовали
    detail = Column(String, default="")                   #доп.контекст (без «сырых» ПДн)
    level = Column(String, default="info")                #info | warn | error


class WebAuthnCredential(Base):
    """Passkey (WebAuthn) — публичный ключ пользователя для входа по биометрии (Face ID/
    отпечаток) БЕЗ пароля. Приватный ключ НИКОГДА не покидает устройство пользователя;
    сервер хранит только публичную часть и проверяет ею подпись при входе. `sign_count`
    растёт при каждом использовании — защита от клонирования ключа. Серверная деталь
    доступа — НЕ входит в SYNC_MODELS."""
    __tablename__ = "webauthn_credentials"
    credential_id = Column(String, primary_key=True)   #base64url id ключа (от аутентификатора)
    login = Column(String, index=True, default="")     #чей ключ
    public_key = Column(String, default="")            #base64url COSE-публичный ключ
    sign_count = Column(Integer, default=0)            #счётчик подписей (анти-клон)
    transports = Column(String, default="")            #csv: internal,hybrid,usb…
    device_name = Column(String, default="")           #как показать пользователю
    created_at = Column(String, default="")
    last_used = Column(String, default="")


class ScheduleOverride(Base):
    """Правка расписания администратором ПОВЕРХ портала (overlay).

    Расписание тянется с portal.esstu.ru (read-only). Здесь админ точечно правит его для
    группы: `action='set'` — задать/заменить пару в ячейке (неделя, день, номер пары),
    `action='remove'` — скрыть портальную пару в этой ячейке. При выдаче расписания
    группы правки НАКЛАДЫВАЮТСЯ на портальные данные (см. web._apply_overrides). Так
    работает и для колледжей без портала (там просто пустая основа + ручные пары).
    Серверная деталь — НЕ входит в SYNC_MODELS (десктопу это не синхронизируется)."""
    __tablename__ = "schedule_overrides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_name = Column(String, index=True, default="")
    week = Column(Integer, default=1)          #1 (I неделя) / 2 (II неделя)
    day = Column(String, default="")           #короткое имя: Пнд Втр Срд Чтв Птн Сбт
    pair_no = Column(Integer, default=0)        #номер пары в дне
    action = Column(String, default="set")      #set | remove
    subject = Column(String, default="")
    time = Column(String, default="")
    room = Column(String, default="")
    teacher = Column(String, default="")
    kind = Column(String, default="")           #Лекция/Практика и т.п.
    updated_at = Column(String, default="")
    deleted = Column(Boolean, default=False)


#Карта «имя сущности → модель» для обобщённого синка push/pull.
#term_grades включены: десктоп теперь ведёт итоговые оценки/ведомости (аттестацию)
#наравне с вебом — данные общие через синк (ключ f|n|subject|year|semester).
SYNC_MODELS = {
    "users": User,
    "groups": Group,
    "subjects": Subject,
    "lessons": Lesson,
    "grades": Grade,
    "term_grades": TermGrade,
    "config": ConfigKV,
}
