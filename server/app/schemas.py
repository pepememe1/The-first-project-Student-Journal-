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
    #refresh-токен для тихого обновления access (клиент хранит его зашифрованно).
    #Пустой — если эндпоинт не выдаёт новый refresh (/auth/refresh переиспользует прежний).
    refresh_token: str = ""


class RefreshIn(BaseModel):
    """Обмен refresh-токена на новый access (тихое обновление сессии)."""
    refresh_token: str


class RevokeIn(BaseModel):
    """Отзыв сессии админом: по jti конкретной сессии ИЛИ по логину (все сессии юзера)."""
    jti: str = ""
    login: str = ""


class BootstrapIn(BaseModel):
    """Создание первого администратора (работает только если админа ещё нет)."""
    login: str
    password: str
    full_name: str = "Администратор"


#Барьер подтверждения устройств (см. connect.py / routers/connect.py)
class ConnectRequestIn(BaseModel):
    """Запрос нового ПК на подключение. hostname — для опознания админом в списке."""
    device_id: str
    hostname: str = ""


class ConnectVerifyIn(BaseModel):
    """Ввод 6-значного кода, который сообщил администратор."""
    device_id: str
    code: str


class DeviceActionIn(BaseModel):
    """Действие администратора над запросом (принять/отклонить)."""
    device_id: str
