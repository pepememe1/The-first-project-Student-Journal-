"""
vector_llm.py — Серверная LLM-озвучка «Вектора» (порт vector/llm.py + prompts.py).

Принцип тот же, что на десктопе (анти-галлюцинации): числа/факты уже посчитаны SQL'ом
(vector_ask), модель их НЕ трогает — только переформулирует готовый текст в стиле
Вектора. Провайдер и ключи берутся из СИНХРОНИЗИРОВАННОГО конфига (ConfigKV 'config',
приезжает с десктопа): vector_llm, gigachat_credentials, gigachat_scope, local_model.

VPS в РФ → GigaChat отсюда работает (в отличие от зарубежных IP). Любая ошибка/
недоступность LLM → тихий откат на исходный фактический текст (сайт не ломается).
"""
import os

VECTOR_PERSONA = """\
Ты — Вектор, тигр-маскот Технологического колледжа ВСГУТУ и голос его цифрового \
журнала. Ты дружелюбный, спокойный и точный помощник: говоришь тепло, но по делу, \
на русском языке, коротко (1–4 предложения). Лёгкая бодрость допустима, но без \
кривляния и без избытка эмодзи (максимум один уместный).

ЖЕЛЕЗНЫЕ ПРАВИЛА:
1. Ты НИКОГДА не придумываешь и не пересчитываешь числа, имена, даты или оценки. \
Ты работаешь ТОЛЬКО с фактами, которые тебе дали в блоке ДАННЫЕ. Если нужного \
факта там нет — честно скажи, что таких данных у тебя нет, и не угадывай.
2. Ты не даёшь медицинских, юридических и иных профессиональных заключений.
3. Ты не раскрываешь данные одних студентов другим. Если спрашивает студент — \
говоришь только о нём самом.
4. Никаких рассуждений вслух и преамбул вроде «Согласно данным...». Просто \
дружелюбный ответ по сути.
5. НИКОГДА не подставляй заготовки-плейсхолдеры и уклончивые заглушки: «[укажите \
средний балл]», «[перечислите фамилии]», «такой-то», «вот здесь», «N» и т.п. Если \
конкретного числа или имени НЕТ в блоке ДАННЫЕ — просто НЕ упоминай эту метрику. \
Лучше короткий ответ строго по имеющимся фактам, чем шаблон с пропусками.
6. Не превращай справку/приветствие в отчёт: если в ДАННЫХ нет цифр, а есть только \
описание того, о чём можно спросить, — передай это как приглашение задать вопрос, \
не выдумывая никаких показателей.
"""

_ROLE_HINT = {
    "student": "Обращаешься к студенту лично, поддерживающе.",
    "teacher": "Обращаешься к преподавателю как к коллеге, по-деловому.",
    "admin":   "Обращаешься к администратору, сухо и по существу.",
}


def _build_voicing_prompt(facts_text: str, role: str, user_question: str) -> list:
    system = VECTOR_PERSONA + "\n" + _ROLE_HINT.get(role, "")
    user = (f"Вопрос пользователя: {user_question}\n\n"
            f"ДАННЫЕ (только из них можно брать факты):\n{facts_text}\n\n"
            f"Озвучь ответ по этим данным в стиле Вектора.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _voice_gigachat(cfg: dict, facts_text: str, role: str, question: str) -> str:
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages
    creds = cfg.get("gigachat_credentials", "")
    if not creds:
        return facts_text
    with GigaChat(credentials=creds,
                  scope=cfg.get("gigachat_scope", "GIGACHAT_API_B2B"),
                  model=cfg.get("gigachat_model", "GigaChat"),
                  verify_ssl_certs=False, timeout=25.0) as client:
        msgs = _build_voicing_prompt(facts_text, role, question)
        chat = Chat(messages=[Messages(role=m["role"], content=m["content"]) for m in msgs],
                    temperature=0.3)
        return client.chat(chat).choices[0].message.content.strip()


def _voice_ollama(cfg: dict, facts_text: str, role: str, question: str) -> str:
    import requests
    host = (cfg.get("local_host") or "http://localhost:11434").rstrip("/")
    msgs = _build_voicing_prompt(facts_text, role, question)
    r = requests.post(host + "/api/chat",
                      json={"model": cfg.get("local_model", "qwen2.5:3b"),
                            "messages": msgs, "stream": False,
                            "options": {"temperature": 0.3}}, timeout=60)
    return r.json()["message"]["content"].strip()


def voice(cfg: dict, facts_text: str, role: str = "student", question: str = "") -> str:
    """Озвучить готовый фактический текст выбранным провайдером. Провайдер и ключи — из
    cfg (синхронизированный конфиг). offline или любая ошибка → вернуть текст как есть."""
    cfg = cfg or {}
    #Аварийный тумблер: GRADEBOOK_VECTOR_LLM=off принудительно отключает озвучку на бою.
    if os.environ.get("GRADEBOOK_VECTOR_LLM", "").strip().lower() == "off":
        return facts_text
    kind = (cfg.get("vector_llm") or "offline").strip()
    try:
        if kind == "gigachat":
            return _voice_gigachat(cfg, facts_text, role, question) or facts_text
        if kind in ("local", "ollama"):
            return _voice_ollama(cfg, facts_text, role, question) or facts_text
    except Exception as e:
        #Не роняем ответ: факты уже верные, LLM лишь переформулировка.
        print(f"[vector_llm] озвучка не удалась ({kind}), отдаю факты как есть: {e}")
    return facts_text


# ── СВОБОДНЫЙ ЧАТ (small-talk) — с редиректом к учёбе и запретом решать задачи ────────
# Просьба заказчика: с Вектором можно перекинуться парой фраз (погода, настроение), но он
# мягко возвращает к учёбе и НЕ решает задания в чате (не «решебник»). Данные журнала здесь
# не выдумываем — их дают ИНТЕНТЫ (SQL). Тут только живой, но управляемый разговор.
_SMALLTALK_RULES = """\
Пользователь написал НЕ по журналу (болтовня, погода, настроение, «как дела»). Правила:
1. Можно коротко (1–2 фразы) по-доброму поддержать разговор, а затем МЯГКО вернуть к учёбе:
   предложи спросить про оценки, средний балл, пропуски или расписание.
2. СТРОГО НЕ РЕШАЙ учебные ЗАДАЧИ в чате: примеры, уравнения, задачи, код, переводы,
   сочинения, рефераты, ответы на тесты. Если просят «реши / посчитай / напиши / переведи /
   сделай задание» — по-доброму откажись («я помощник журнала, а не решебник — лучше
   разберёмся вместе или спроси преподавателя») и НЕ давай решение даже частично.
3. Не выдумывай данные журнала (оценки, имена, списки, расписание) — предложи команды:
   «мои оценки», «средний балл», «какие группы», «расписание».
4. Не давай медицинских/юридических/политических заключений.
Коротко, на русском, максимум один эмодзи."""


def _freechat_messages(question: str, role: str) -> list:
    system = VECTOR_PERSONA + "\n" + _ROLE_HINT.get(role, "") + "\n\n" + _SMALLTALK_RULES
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


def _free_offline(role: str) -> str:
    return ("С радостью бы поболтал, но сейчас я без ИИ-модели. Зато точно помогу по журналу: "
            "спроси про оценки, средний балл, пропуски или расписание. 🐯")


def _chat_gigachat(cfg: dict, messages: list) -> str:
    from gigachat import GigaChat
    from gigachat.models import Chat, Messages
    creds = cfg.get("gigachat_credentials", "")
    if not creds:
        return ""
    with GigaChat(credentials=creds, scope=cfg.get("gigachat_scope", "GIGACHAT_API_B2B"),
                  model=cfg.get("gigachat_model", "GigaChat"),
                  verify_ssl_certs=False, timeout=25.0) as client:
        chat = Chat(messages=[Messages(role=m["role"], content=m["content"]) for m in messages],
                    temperature=0.5)
        return client.chat(chat).choices[0].message.content.strip()


def _chat_ollama(cfg: dict, messages: list) -> str:
    import requests
    host = (cfg.get("local_host") or "http://localhost:11434").rstrip("/")
    r = requests.post(host + "/api/chat",
                      json={"model": cfg.get("local_model", "qwen2.5:3b"),
                            "messages": messages, "stream": False,
                            "options": {"temperature": 0.5}}, timeout=60)
    return r.json()["message"]["content"].strip()


def free_chat(cfg: dict, question: str, role: str = "student") -> str:
    """Свободный ответ на НЕжурнальный вопрос: короткий small-talk → возврат к учёбе, без
    решения задач. Нет провайдера/ошибка → мягкий офлайн-редирект (чат не ломается)."""
    cfg = cfg or {}
    if os.environ.get("GRADEBOOK_VECTOR_LLM", "").strip().lower() == "off":
        return _free_offline(role)
    kind = (cfg.get("vector_llm") or "offline").strip()
    try:
        if kind == "gigachat":
            return _chat_gigachat(cfg, _freechat_messages(question, role)) or _free_offline(role)
        if kind in ("local", "ollama"):
            return _chat_ollama(cfg, _freechat_messages(question, role)) or _free_offline(role)
    except Exception as e:
        print(f"[vector_llm] free_chat не удался ({kind}): {e}")
    return _free_offline(role)
