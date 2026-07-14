"""
vector.py — Серверная озвучка «Вектора» для ДЕСКТОПА (и любого авторизованного клиента).

Зачем. Токен провайдера ИИ (GigaChat) хранится ТОЛЬКО на сервере и больше не
раздаётся на клиентские ПК (см. sync._scope_pull_for_role, 152-ФЗ). Поэтому десктоп,
которому нужно «озвучить» уже посчитанные факты, шлёт их сюда, а сервер переформулирует
их своим провайдером (ключ — из синхронизированного config на сервере).

Анти-галлюцинации сохранены: клиент присылает УЖЕ ГОТОВЫЕ и обезличенные факты (числа
считает клиентский слой intents), модель их не трогает — только стиль. Факты не
сохраняются. При любой ошибке/оффлайне провайдера сервер вернёт факты как есть.
"""
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from .. import webdata as W
from .. import vector_llm

router = APIRouter(prefix="/vector", tags=["vector"])


@router.post("/voice")
def voice(payload: dict = Body(...),
          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Переформулировать готовый фактический текст провайдером сервера.

    Тело: {facts, role?, question?}. Роль по умолчанию — роль пользователя. Токен
    провайдера не раскрывается. Пустые факты → пустой ответ (нечего озвучивать)."""
    facts = (payload.get("facts") or "").strip()
    if not facts:
        return {"text": ""}
    role = (payload.get("role") or user.role or "student")
    question = (payload.get("question") or "")
    cfg = W.load_config(db)
    text = vector_llm.voice(cfg, facts, role, question)
    return {"text": text}
