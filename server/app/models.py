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


#Карта «имя сущности → модель» для обобщённого синка push/pull.
SYNC_MODELS = {
    "users": User,
    "groups": Group,
    "subjects": Subject,
    "lessons": Lesson,
    "grades": Grade,
    "config": ConfigKV,
}
