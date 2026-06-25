"""
vector — ИИ-маскот ВСГУТУ «Вектор».

Архитектура (главное правило: Вектор НИКОГДА не выдумывает цифры):

    вопрос пользователя
        → intents.classify()         распознаём намерение (локально, без сети)
        → intents.<handler>()         реальный SQL к локальной базе → ФАКТЫ
        → privacy.anonymize()         ФИО → «Студент №N» (для облачной LLM)
        → llm.voice()                 LLM только ПЕРЕФОРМУЛИРУЕТ факты
        → privacy.deanonymize()       возвращаем настоящие имена локально
        → engine.VectorResponse       текст + настроение + сами факты

Если LLM недоступна (офлайн) — фразы собирает локальный шаблонизатор, поэтому
Вектор работает всегда. Это и есть «офлайн-first как преимущество».
"""

from .engine import VectorEngine, VectorResponse, VectorScope
from .insights import compute_insights, InsightCard
from .llm import get_provider, OfflineTemplateProvider, GigaChatProvider

__all__ = [
    "VectorEngine", "VectorResponse", "VectorScope",
    "compute_insights", "InsightCard",
    "get_provider", "OfflineTemplateProvider", "GigaChatProvider",
]
