"""
translate_service.py — перевод сообщений мессенджера.

━━ ЧЕМ ПЕРЕВОДИМ (29.08.2026: перенесено с Google Translate на локальный Argos) ━━
Переводит **Argos Translate** — офлайновый нейропереводчик (CTranslate2 + SentencePiece,
лицензия MIT, модели CC0). Работает НА НАШЕЙ МАШИНЕ: ни текст, ни его часть никуда
не отправляются.

🔒 ПОЧЕМУ ЗАМЕНИЛИ, ХОТЯ РАБОТАЛО. Прежняя реализация звала `deep-translator`. Библиотека
открытая, и это вводило в заблуждение: собственного переводчика в ней нет вовсе — это
HTTP-клиент, который дёргает веб-форму translate.google.com теми же запросами, что и
браузер. То есть текст ЛИЧНОЙ ПЕРЕПИСКИ студентов уходил иностранному юридическому лицу
целиком и без обезличивания. Юридически это трансграничная передача персональных данных
(ст. 12 152-ФЗ), требующая уведомления Роскомнадзора ДО начала, а договора с Google у
нас нет и быть не могло — использование неофициальной обёртки прямо противоречит его
правилам. То есть отсутствие договора не смягчало ситуацию, а усугубляло: поручение
обработки по ч. 3 ст. 6 152-ФЗ оформить было не с кем.
Теперь передачи нет ВООБЩЕ, поэтому ни уведомления, ни согласия, ни поручения не
требуется — вопрос закрыт по построению, а не регламентом, который однажды забудут.

⚠️ **GOOGLE УДАЛЁН ЦЕЛИКОМ, А НЕ ОСТАВЛЕН ЗА ФЛАГОМ.** Флаг «использовать Google» —
это одна строка конфигурации между перепиской колледжа и чужим сервером, и однажды её
переключат «на время, чтобы проверить». Здесь протащить текст наружу нечем: в модуле нет
ни одного сетевого вызова. Держит `test_translate_never_reaches_the_network`.

⚠️ ЦЕНА, НАЗВАННАЯ ЧЕСТНО. Качество ниже, чем у Google, особенно на китайском: прямой
пары ru↔zh у Argos нет, перевод идёт ПИВОТОМ через английский (ru→en→zh), то есть
потери накапливаются дважды. Для рабочей переписки это приемлемо, для художественного
текста — нет. Первый перевод после запуска дольше остальных: модель грузится с диска.

⚠️ Модели ставятся ОТДЕЛЬНО (`tools/install_argos_models.py`), в репозиторий не кладутся:
четыре пары весят сотни мегабайт. Пакета или моделей нет → `translate()` честно
возвращает `ok=False` с причиной, а НЕ возвращает исходный текст молча. Молчаливый
возврат хуже отказа: человек решит, что перевод сделан, и что собеседник написал
именно это.

⚠️ ПРИВАТНОСТЬ ВНУТРИ. Перевод по-прежнему остаётся местом, где текст личной переписки
обрабатывается целиком и без маскирования ФИО (для сводки §18 мы их маскируем, здесь
нельзя — человек читает результат и должен видеть, о ком речь). Но теперь обработка
происходит на том же сервере, что и сама переписка, то есть новых получателей не
появляется. По умолчанию функция ВЫКЛЮЧЕНА; перевод входящих делается по кнопке;
автоперевод исходящих человек включает сам и видит результат ДО отправки.
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

#Язык-посредник для пар, между которыми у Argos нет прямой модели. У нас это ru↔zh:
#в каталоге Argos есть ru↔en и en↔zh, но не ru↔zh напрямую.
#⚠️ Коды языков Argos — обычные ISO 639-1, то есть РОВНО наши ключи LANGUAGES. Таблица
#соответствий, которая была нужна Google (у него упрощённый китайский «zh-CN», а не
#«zh»), здесь не нужна вовсе — и это на одну молчаливую ошибку меньше.
_PIVOT = "en"

#Сколько символов переводим за раз. Лимит сообщения и так 4000, но длинная простыня —
#секунды ожидания и риск обрыва; переводим начало и честно помечаем обрез.
_MAX_CHARS = 2000

#⚠️ ПУЛ ПОТОКОВ И ЖЁСТКИЙ ТАЙМАУТ ОСТАЮТСЯ, ХОТЯ СЕТИ БОЛЬШЕ НЕТ, — причина сменилась,
#необходимость нет. Раньше защищались от зависшего HTTP-запроса; теперь от того, что
#Argos считает НА ПРОЦЕССОРЕ и синхронно. На боевой машине одно ядро (§13), и вызов
#прямо в `async def` заморозил бы весь сервер: журнал, сокеты и /health — это уже
#записанный инвариант, купленный дефектом с Whisper.
#Значение подняли с 8 до 25 секунд: первый перевод после запуска включает ЗАГРУЗКУ
#МОДЕЛИ С ДИСКА, и на медленном диске восьми секунд не хватало — перевод «не работал»
#ровно один раз после каждого рестарта, что отлаживается особенно неприятно.
_REQUEST_TIMEOUT_S = 25
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="translate")

#Кэш переводов в памяти процесса: одну и ту же реплику в групповом чате открывают
#несколько человек, и гонять модель повторно незачем. Ключ — хеш текста и пары языков.
#Ограничен по размеру: без предела он растёт вместе с перепиской и съедает 960 МБ VPS.
_CACHE: dict = {}
_CACHE_LIMIT = 500


def _key(text: str, src: str, dst: str) -> str:
    return hashlib.sha256(f"{src}|{dst}|{text}".encode()).hexdigest()


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


#Загруженные переводчики: (откуда, куда) → объект Argos. Загрузка модели с диска стоит
#секунд, а пар у нас всего четыре — держим их в памяти процесса на весь срок его жизни.
_ENGINES: dict = {}


def engine_available() -> bool:
    """Установлен ли пакет argostranslate. Без него перевод честно не работает."""
    try:
        import argostranslate.translate  # noqa: F401
        return True
    except Exception:
        return False


def installed_pairs() -> list:
    """Какие пары языков реально установлены — для диагностики и админки.

    Спрашиваем У БИБЛИОТЕКИ, а не сверяем со своим списком: наш список — это
    намерение, а установлено на машине может быть другое. Расхождение этих двух
    величин и есть то, что надо показать администратору."""
    try:
        import argostranslate.translate as at
        langs = at.get_installed_languages()
        out = []
        for a in langs:
            for b in langs:
                if a.code != b.code and a.code in LANGUAGES and b.code in LANGUAGES:
                    try:
                        if a.get_translation(b):
                            out.append(f"{a.code}->{b.code}")
                    except Exception:
                        pass
        return sorted(out)
    except Exception:
        return []


def _direct(src: str, dst: str):
    """Переводчик Argos для ПРЯМОЙ пары или None, если такой модели не установлено."""
    if (src, dst) in _ENGINES:
        return _ENGINES[(src, dst)]
    import argostranslate.translate as at
    langs = {l.code: l for l in at.get_installed_languages()}
    a, b = langs.get(src), langs.get(dst)
    if not a or not b:
        return None
    try:
        engine = a.get_translation(b)
    except Exception:
        engine = None
    _ENGINES[(src, dst)] = engine
    return engine


def _argos_translate(text: str, src: str, dst: str) -> str:
    """Один перевод локальной моделью. Синхронный и процессорный — зовётся только из
    пула потоков (см. комментарий про таймаут выше).

    ⚠️ ПИВОТ ЧЕРЕЗ АНГЛИЙСКИЙ ДЕЛАЕМ САМИ, а не полагаемся на то, что библиотека
    догадается. Свежие версии Argos умеют строить составной путь, старые — нет, и
    поведение молча зависело бы от версии пакета на конкретной машине. Явные две
    ступени ведут себя одинаково везде.
    """
    if src == AUTO:
        src = detect(text) or "en"
    if src == dst:
        return text
    engine = _direct(src, dst)
    if engine is not None:
        return engine.translate(text)
    #Прямой модели нет — идём через посредника. У нас это ровно случай ru↔zh.
    if src != _PIVOT and dst != _PIVOT:
        first, second = _direct(src, _PIVOT), _direct(_PIVOT, dst)
        if first is not None and second is not None:
            return second.translate(first.translate(text))
    raise RuntimeError(f"нет модели перевода {src}->{dst}")


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

    if not engine_available():
        #Честный отказ с ПРИЧИНОЙ, а не «временно недоступен»: пакета нет — значит его
        #надо поставить, и администратор должен прочитать именно это, а не гадать про
        #сеть, которой здесь больше нет вовсе.
        return {"ok": False, "text": "", "detected": detected,
                "reason": "Переводчик не установлен на сервере."}

    out = ""
    try:
        future = _executor.submit(_argos_translate, body_cut, src, dst)
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
