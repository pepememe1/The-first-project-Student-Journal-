"""
llm.py — Провайдеры озвучки для Вектора.

Все провайдеры получают на вход УЖЕ ГОТОВЫЕ ФАКТЫ (и, для облачных, уже обезличенные)
и только переформулируют их в живую фразу. Ни один провайдер не считает и не
придумывает числа — это сделал слой intents.

Провайдеры:
  • OfflineTemplateProvider — без сети. Возвращает факты как аккуратную фразу.
    Гарантирует, что Вектор работает всегда (офлайн-first как преимущество).
  • GigaChatProvider — отечественная LLM Сбера (scope B2B). RU-юрисдикция, можно
    подписать поручение на обработку ПДн. Получает только обезличенный текст.
  • LocalModelProvider — локальная модель через ollama (http://localhost:11434).
    Ничего наружу не уходит вообще — это «премиум»-режим приватности для вуза.

Фабрика get_provider(config) выбирает провайдера по настройке, с безопасным
откатом на офлайн-шаблон при любой ошибке.
"""

from .prompts import build_voicing_prompt


def explain_giga_error(exc) -> str:
    """
    Превращает техническую ошибку GigaChat в понятную подсказку.
    Возвращает короткую строку: что произошло и что делать.
    """
    msg = str(exc)
    low = msg.lower()
    if "no module named" in low or ("gigachat" in low and "import" in low):
        return "Не установлен пакет. Выполните в консоли: pip install gigachat"
    if "10061" in msg or "refused" in low:
        return ("Соединение отклонено — порт 9443 закрыт файрволом или сетью колледжа. "
                "Попробуйте другую сеть (раздача с телефона).")
    if ("10060" in msg or "timed out" in low or "timeout" in low
            or "getaddrinfo failed" in low or "11001" in msg
            or "max retries" in low or ("connection" in low and "refused" not in low)):
        return ("Нет связи с серверами GigaChat (таймаут). Почти всегда это VPN/прокси "
                "— GigaChat работает только с российских IP. Выключите VPN и повторите. "
                "Также проверьте файрвол/антивирус (порт 9443) и сеть колледжа.")
    if "401" in msg or "unauthorized" in low or "invalid" in low:
        return ("Ключ или SCOPE не подходят. Для персонального ключа выберите "
                "SCOPE = GIGACHAT_API_PERS.")
    if "ssl" in low or "certificate" in low:
        return ("Ошибка сертификата. В настройках стоит обход проверки; если она "
                "повторяется — установите корневой сертификат Минцифры.")
    return f"Не удалось подключиться: {msg}"


class LLMProvider:
    """Базовый интерфейс. voice() возвращает строку-ответ Вектора."""
    name = "base"

    def voice(self, facts_text: str, role: str = "student",
              user_question: str = "") -> str:
        raise NotImplementedError

    def free_chat(self, question: str, role: str = "student") -> str:
        """
        Свободный ответ на вопрос, которого нет в пуле команд.
        У офлайн-провайдера честно признаётся, что отвечает только по журналу.
        Облачные/локальные модели переопределяют этот метод.
        """
        from .faq import unknown_offline_text
        return unknown_offline_text(role)

    def available(self) -> bool:
        return True


#Офлайн-шаблонизатор (по умолчанию и как фолбэк)
class OfflineTemplateProvider(LLMProvider):
    """
    Никакой сети. Факты уже сформулированы человекочитаемо в intents (facts_text);
    здесь они оборачиваются в тёплый, развёрнутый ответ (faq.friendly_wrap):
    приветственное вступление → точные факты из SQL → подсказка следующего шага.
    Цифры не трогаем — только тон.
    """
    name = "offline"

    def voice(self, facts_text: str, role: str = "student",
              user_question: str = "", intent: str = "") -> str:
        from .faq import friendly_wrap
        return friendly_wrap(intent or "average", facts_text, role)


#GigaChat (отечественная облачная LLM, scope B2B)
class GigaChatProvider(LLMProvider):
    """
    Требует пакет gigachat (pip install gigachat) и ключ авторизации B2B.
    ВАЖНО: сюда передавать только ОБЕЗЛИЧЕННЫЙ facts_text (см. vector.privacy).
    Сертификаты Сбера — российский УЦ, поэтому verify_ssl_certs=False либо
    предварительно установить корневой сертификат Минцифры.
    """
    name = "gigachat"

    def __init__(self, credentials: str, scope: str = "GIGACHAT_API_B2B",
                 model: str = "GigaChat", verify_ssl: bool = False,
                 timeout: float = 25.0):
        self.credentials = credentials
        self.scope = scope
        self.model = model
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._client = None

    def available(self) -> bool:
        try:
            import gigachat  # noqa: F401
            return bool(self.credentials)
        except ImportError:
            return False

    def _ensure_client(self):
        if self._client is None:
            from gigachat import GigaChat
            self._client = GigaChat(
                credentials=self.credentials,
                scope=self.scope,
                model=self.model,
                verify_ssl_certs=self.verify_ssl,
                timeout=self.timeout,
            )
        return self._client

    def voice(self, facts_text: str, role: str = "student",
              user_question: str = "") -> str:
        from gigachat.models import Chat, Messages
        msgs = build_voicing_prompt(facts_text, role, user_question)
        client = self._ensure_client()
        chat = Chat(messages=[Messages(role=m["role"], content=m["content"])
                              for m in msgs], temperature=0.3)
        resp = client.chat(chat)
        return resp.choices[0].message.content.strip()

    def free_chat(self, question: str, role: str = "student") -> str:
        """Вопрос вне пула команд. Вопрос уже обезличен (engine)."""
        from gigachat.models import Chat, Messages
        from .prompts import build_free_chat_prompt
        msgs = build_free_chat_prompt(question, role)
        client = self._ensure_client()
        chat = Chat(messages=[Messages(role=m["role"], content=m["content"])
                              for m in msgs], temperature=0.5)
        resp = client.chat(chat)
        return resp.choices[0].message.content.strip()


#Локальная модель через ollama (ничего наружу не уходит)
class LocalModelProvider(LLMProvider):
    name = "local"

    def __init__(self, model: str = "qwen2.5:3b",
                 host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")

    def available(self) -> bool:
        try:
            import requests
            r = requests.get(self.host + "/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def voice(self, facts_text: str, role: str = "student",
              user_question: str = "") -> str:
        import requests
        msgs = build_voicing_prompt(facts_text, role, user_question)
        r = requests.post(
            self.host + "/api/chat",
            json={"model": self.model, "messages": msgs, "stream": False,
                  "options": {"temperature": 0.3}},
            timeout=60,
        )
        return r.json()["message"]["content"].strip()

    def free_chat(self, question: str, role: str = "student") -> str:
        import requests
        from .prompts import build_free_chat_prompt
        msgs = build_free_chat_prompt(question, role)
        r = requests.post(
            self.host + "/api/chat",
            json={"model": self.model, "messages": msgs, "stream": False,
                  "options": {"temperature": 0.5}},
            timeout=60,
        )
        return r.json()["message"]["content"].strip()


#Озвучка через СЕРВЕР (токен провайдера ИИ живёт на сервере, не на клиентских ПК)
class ServerProvider(LLMProvider):
    """Переформулирует факты, вызывая эндпоинт сервера (/vector/voice). Ключ GigaChat
    хранится ТОЛЬКО на сервере (152-ФЗ: не раздаём токен колледжа по сотням ПК). Десктоп
    шлёт УЖЕ ГОТОВЫЕ и обезличенные факты (движок обезличивает, как для облачных
    провайдеров), сервер их только озвучивает. Адрес/токен берём у фонового синкера.

    Свободный чат (free_chat) не проксируем: остаётся честный офлайн-ответ (базовый
    класс) — на клиентских ПК без ключа это ожидаемо, а факты всё равно озвучиваются."""
    name = "server"

    @staticmethod
    def _auth():
        try:
            from sync.sync_runner import current_auth
            return current_auth()          #(url, token)
        except Exception:
            return ("", "")

    def available(self) -> bool:
        url, token = self._auth()
        return bool(url and token)

    def voice(self, facts_text: str, role: str = "student",
              user_question: str = "") -> str:
        url, token = self._auth()
        if not (url and token):
            raise RuntimeError("нет адреса сервера или токена для серверной озвучки")
        from sync.sync_client import SyncClient
        return SyncClient(url, token).voice(facts_text, role=role, question=user_question)


#  Фабрика
def get_provider(config: dict | None = None) -> LLMProvider:
    """
    config (из настроек, хранится в kv_store['config']):
        {"vector_llm": "offline" | "gigachat" | "local",
         "gigachat_credentials": "...", "gigachat_scope": "GIGACHAT_API_B2B",
         "gigachat_model": "GigaChat", "local_model": "qwen2.5:3b"}
    Любая ошибка/недоступность → откат на офлайн-шаблон.
    """
    config = config or {}
    kind = config.get("vector_llm", "offline")
    try:
        if kind == "gigachat":
            creds = config.get("gigachat_credentials", "")
            if creds:
                #Ключ есть локально (админ-ПК) — ходим в GigaChat напрямую.
                p = GigaChatProvider(
                    credentials=creds,
                    scope=config.get("gigachat_scope", "GIGACHAT_API_B2B"),
                    model=config.get("gigachat_model", "GigaChat"),
                )
                if p.available():
                    return p
            #Ключа локально нет (не-админ: токен остался на сервере) → озвучка через сервер.
            sp = ServerProvider()
            return sp if sp.available() else OfflineTemplateProvider()
        if kind == "local":
            p = LocalModelProvider(model=config.get("local_model", "qwen2.5:3b"))
            return p if p.available() else OfflineTemplateProvider()
    except Exception:
        pass
    return OfflineTemplateProvider()
