"""
vector.py — Серверная озвучка «Вектора» для ДЕСКТОПА (и любого авторизованного клиента).

Зачем. Токен провайдера ИИ (GigaChat) хранится ТОЛЬКО на сервере и больше не
раздаётся на клиентские ПК (см. sync._scope_pull_for_role, 152-ФЗ). Поэтому десктоп,
которому нужно «озвучить» уже посчитанные факты, шлёт их сюда, а сервер переформулирует
их своим провайдером (ключ — из синхронизированного config на сервере).

Анти-галлюцинации сохранены: клиент присылает УЖЕ ГОТОВЫЕ факты (числа считает его
локальный сервер тем же `routers/web/vector.py`), модель их не трогает — только стиль.
Факты не сохраняются. При любой ошибке/оффлайне провайдера сервер вернёт факты как есть.

⚠️ ОБЕЗЛИЧИВАНИЯ ЗДЕСЬ НЕТ, И ПРОВЕРКИ НА ФИО ТОЖЕ (поправка 14.10.2026; до неё тут
стояло «присылает обезличенные факты» — шага обезличивания в продукте нет с 15.08).
Решение «можно ли отдавать текст модели» принимает ВЫЗЫВАЮЩИЙ: локальный сервер программы
до похода сюда сверяет вопрос с фамилиями (`_names_a_person`) и не зовёт озвучку для
ответов со списками людей (`no_voice`). Эта ручка ему доверяет — второй линии защиты на
бою нет, и любой вошедший клиент может прислать сюда произвольный текст. Открытая находка
Полковника 14.10.2026 (`docs/HISTORY.md`, запись 66).
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

    Тело: {facts, role?, question?, locale?, mode?}. Роль по умолчанию — роль
    пользователя. Токен провайдера не раскрывается. Пустые факты → пустой ответ.

    `mode="chat"` — свободный разговор (вопрос не про журнал, `vector_llm.free_chat`):
    локальный Вектор программы ключа не имеет (26.09.2026, см. `vector_llm.set_remote`)
    и просит здесь и его. Данных журнала в таком запросе нет — только сам вопрос.
    `locale` — язык интерфейса; без поля — русский, как у прежних сборок."""
    role = (payload.get("role") or user.role or "student")
    question = (payload.get("question") or "")
    locale = (payload.get("locale") or "ru")
    cfg = W.load_config(db)
    #🔒 ФИО НЕ УХОДИТ В МОДЕЛЬ И ОТСЮДА (15.10.2026, находка Полковника 14.10.2026).
    #До этого ручка доверяла вызывающему: локальный сервер программы сверял вопрос с
    #фамилиями сам, а любой вошедший клиент мог прислать сюда произвольный текст, и он
    #уходил внешнему сервису. Проверка — та же одна дверь, что у сайта.
    from .web.vector import _names_a_person
    if payload.get("mode") == "chat":
        if not question.strip():
            return {"text": ""}
        if _names_a_person(question, db):
            return {"text": vector_llm.offline_reply(role, locale)}
        return {"text": vector_llm.free_chat(cfg, question, role, "", locale)}
    facts = (payload.get("facts") or "").strip()
    if not facts:
        return {"text": ""}
    if _names_a_person(f"{facts}\n{question}", db):
        return {"text": facts}          #как при любом отказе озвучки — факты как есть
    return {"text": vector_llm.voice(cfg, facts, role, question, locale)}
