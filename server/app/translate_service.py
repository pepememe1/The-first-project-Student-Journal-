"""
translate_service.py — перевод сообщений мессенджера.

━━ ЧЕМ ПЕРЕВОДИМ (3.5.5: перенесено с LLM на Google Translate) ━━
Раньше переводом занималась ТА ЖЕ модель, что и «Вектор» (GigaChat/Ollama) — решение
казалось экономным (второй провайдер не нужен), но на практике LLM ОХОТНО отказывалась
переводить: получив на входе текст, похожий на нарушение «политики сообщества» (мат,
резкость, спор), модель вместо перевода отвечала отказом («извините, не могу помочь с
этим текстом»), и в чате это выглядело так, будто перевод сломан. Прямой переводчик
слов НЕ интерпретирует смысл и НЕ отказывает — переводит буквально, что и требуется.
Библиотека — `deep-translator` (неофициальная, бесплатная, дёргает веб-форму
translate.google.com теми же HTTP-запросами, что и браузер). Осознанный компромисс:
без ключа и без оплаты, но это НЕ публичный контракт Google — теоретически может
перестать отвечать/ограничить по IP без предупреждения. На этот случай `translate()`,
как и раньше, честно возвращает `ok=False` с причиной, а не выдумывает перевод.

⚠️ ПРИВАТНОСТЬ. Перевод — единственное место, где текст личной переписки уходит НАРУЖУ
ЦЕЛИКОМ (третьей стороне, а не на свой сервер, как остальной ИИ-стек). Для сводки (§18)
мы маскируем ФИО, здесь так нельзя: человек читает результат и должен видеть, о ком
речь. Поэтому защита другая:
  • по умолчанию ВЫКЛЮЧЕНО — ни одно сообщение не переводится само;
  • перевод входящих делается ПО КНОПКЕ, то есть по осознанному действию;
  • автоперевод исходящих человек включает сам, и он видит результат ДО отправки.
Интерфейс обязан говорить это прямо, а не прятать в согласии.

━━ ПОЧЕМУ ПЕРЕВОД НЕ ТРОГАЕТ ИСХОДНОЕ СООБЩЕНИЕ ━━
Переведённый текст НИКОГДА не сохраняется вместо оригинала и не уходит собеседнику:
в базе лежит то, что человек написал. Перевод — это способ ПРОЧИТАТЬ чужое сообщение,
а не подменить его. Исключение одно и явное: автоперевод ИСХОДЯЩИХ, где человек сам
попросил отправлять переведённое, — но и там он видит текст до нажатия «отправить».
"""
import concurrent.futures
import hashlib
import logging
import re

log = logging.getLogger("gradebook.translate")

#Языки, между которыми переводим. Список закрытый: открытое поле «любой язык» означало бы
#непроверяемую строку в запросе, а колледжу нужны ровно эти три (плюс автоопределение).
LANGUAGES = {
    "ru": "русский",
    "en": "английский",
    "zh": "китайский",
}
AUTO = "auto"

#Коды Google Translate для НАШИХ трёх языков — упрощённый китайский у него «zh-CN», не
#голое «zh» (deep_translator сверяет код буквально, чужой формат — тихая ошибка запроса).
_GOOGLE_LANG = {"ru": "ru", "en": "en", "zh": "zh-CN"}

#Сколько символов переводим за раз. Лимит сообщения и так 4000, но длинная простыня —
#секунды ожидания и риск обрыва; переводим начало и честно помечаем обрез.
_MAX_CHARS = 2000

#⚠️ У deep_translator НЕТ параметра таймаута — голый requests.get() без сокет-таймаута
#способен зависнуть НАВСЕГДА, если translate.google.com не ответит (не отклонит, а
#именно подвиснет). На одноядерном VPS зависший поток — это постепенно исчерпанный пул
#воркеров. Оборачиваем свой собственный жёсткий таймаут через отдельный пул потоков —
#после него запрос считается неудавшимся (поток-исполнитель донагружается и тихо
#завершится сам позже, это не течёт памятью, просто не блокирует вызывающего).
_REQUEST_TIMEOUT_S = 8
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")

#Кэш переводов в памяти процесса: одну и ту же реплику в групповом чате открывают
#несколько человек, и гонять модель повторно незачем. Ключ — хеш текста и пары языков.
#Ограничен по размеру: без предела он растёт вместе с перепиской и съедает 960 МБ VPS.
_CACHE: dict = {}
_CACHE_LIMIT = 500


def _key(text: str, src: str, dst: str) -> str:
    return hashlib.sha256(f"{src}|{dst}|{text}".encode("utf-8")).hexdigest()


def _remember(key: str, value: str) -> None:
    if len(_CACHE) >= _CACHE_LIMIT:
        #Простое усечение вместо LRU: точность вытеснения тут не стоит структуры данных,
        #промах кэша — это лишний вызов модели, а не ошибка.
        _CACHE.clear()
    _CACHE[key] = value


def detect(text: str) -> str:
    """Грубое определение языка по алфавиту ('' — не определили).

    Специально БЕЗ модели: спрашивать её «какой это язык» ради одной подсказки в
    интерфейсе — лишний сетевой вызов на каждое сообщение. Кириллица/иероглифы/латиница
    различаются пересчётом символов надёжнее, чем это сделает LLM."""
    if not text:
        return ""
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", text))
    han = len(re.findall(r"[一-鿿]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if han and han >= max(cyr, lat):
        return "zh"
    if cyr and cyr >= lat:
        return "ru"
    if lat:
        return "en"
    return ""


def _google_translate(text: str, src: str, dst: str) -> str:
    """Один запрос к Google Translate (deep_translator). Синхронный и потенциально
    БЕЗ таймаута изнутри — вызывающий (translate()) сам оборачивает его в _executor
    с жёстким пределом (_REQUEST_TIMEOUT_S), см. докстринг файла."""
    from deep_translator import GoogleTranslator
    g_src = "auto" if src == AUTO else _GOOGLE_LANG.get(src, "auto")
    g_dst = _GOOGLE_LANG.get(dst, "ru")
    return GoogleTranslator(source=g_src, target=g_dst).translate(text)


def translate(text: str, dst: str, src: str = AUTO) -> dict:
    """Перевести текст. Возвращает {ok, text, detected, reason}.

    Никогда не бросает и никогда не выдумывает: переводчик недоступен → ok=False и
    ПРИЧИНА, а не молчаливый возврат исходного текста. Молчаливый возврат хуже отказа —
    человек решит, что перевод сделан, и что собеседник написал именно это."""
    body = (text or "").strip()
    if not body:
        return {"ok": False, "text": "", "detected": "", "reason": "Пустой текст"}
    if dst not in LANGUAGES:
        return {"ok": False, "text": "", "detected": "", "reason": "Неизвестный язык"}

    detected = detect(body)
    #Уже на нужном языке — не ходим в сеть вовсе.
    if detected == dst and src in (AUTO, detected):
        return {"ok": True, "text": body, "detected": detected, "reason": "same"}

    truncated = len(body) > _MAX_CHARS
    body_cut = body[:_MAX_CHARS]
    key = _key(body_cut, src, dst)
    if key in _CACHE:
        return {"ok": True, "text": _CACHE[key], "detected": detected, "reason": "cache"}

    out = ""
    try:
        future = _executor.submit(_google_translate, body_cut, src, dst)
        out = (future.result(timeout=_REQUEST_TIMEOUT_S) or "").strip()
    except Exception as e:      # noqa: BLE001 — перевод не имеет права ронять чат
        log.warning("перевод не удался: %s", e)
    if not out:
        return {"ok": False, "text": "", "detected": detected,
                "reason": "Переводчик временно недоступен — попробуйте ещё раз чуть позже."}
    if truncated:
        out += " …"
    _remember(key, out)
    return {"ok": True, "text": out, "detected": detected, "reason": ""}


#Настройки перевода в prefs пользователя. Ключи и значения читает СЕРВЕР (автоперевод
#исходящих), поэтому приводим их к строгому виду там же, где остальные prefs.
_FIELDS = ("incoming_from", "incoming_to", "outgoing_from", "outgoing_to")
DEFAULTS = {"incoming_from": AUTO, "incoming_to": "ru",
            "outgoing_from": AUTO, "outgoing_to": "en", "auto": False}


def sanitize_prefs(box) -> dict:
    """Привести `prefs.translate` к строгому виду: только известные языки и «да/нет».

    Мусор здесь — не косметика: по этим полям сервер решает, переводить ли исходящее
    сообщение и на какой язык. Незнакомый код языка ушёл бы прямо в промпт."""
    if not isinstance(box, dict):
        return {}
    out = {}
    for field in _FIELDS:
        value = str(box.get(field, "")).strip().lower()
        allowed = set(LANGUAGES) | ({AUTO} if field.endswith("_from") else set())
        if value in allowed:
            out[field] = value
    out["auto"] = bool(box.get("auto"))
    return out
