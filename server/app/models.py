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
    name = Column(String, default="")
    group_name = Column(String, default="")            #для студента
    subjects = Column(JSON, default=list)              #для преподавателя
    group_assignments = Column(JSON, default=dict)     #для преподавателя
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


#Карта «имя сущности → модель» для обобщённого синка push/pull.
SYNC_MODELS = {
    "users": User,
    "groups": Group,
    "subjects": Subject,
    "lessons": Lesson,
    "grades": Grade,
    "config": ConfigKV,
}
