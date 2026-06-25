"""
schemas.py — Pydantic-схемы запросов/ответов API.

Синк (push/pull) использует свободные словари (dict), чтобы не дублировать здесь
структуру каждой сущности — формат описан в routers/sync.py и README.
"""
from pydantic import BaseModel


class LoginIn(BaseModel):
    login: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str = ""


class BootstrapIn(BaseModel):
    """Создание первого администратора (работает только если админа ещё нет)."""
    login: str
    password: str
    full_name: str = "Администратор"
