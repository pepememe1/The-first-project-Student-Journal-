"""
vector.py — «Вектор»: ответы по фактам журнала, голосовой ввод, озвучка, локализация.

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы
#Расписание группы уже собрано в модуле расписания (мердж портала с правками админа) —
#Вектор отвечает на «что сегодня» ТЕМИ ЖЕ данными, что показывает страница.
from .schedule import _group_schedule      # noqa: F401
#Пул потоков для синхронного CPU-heavy кода (распознавание речи), см. vector_stt.
from starlette.concurrency import run_in_threadpool      # noqa: E402


# «ВЕКТОР» ─────────────────────────────────────────────────────────────────────────
#Интенты со СТАТИЧНЫМ текстом (приветствие/справка/благодарность/факты о ВСГУТУ). Их
#НЕЛЬЗЯ гонять через LLM: там нечего переформулировать — это готовая справка, а не данные.
#Модель видит в ней НАЗВАНИЯ метрик («средний балл», «должники», «зона риска») без цифр и
#дописывает шаблон с плейсхолдерами («Средний балл по группам: [укажите средние баллы]») —
#ровно та выдумка, которую продукт обещает не делать (§5). LLM озвучивает ТОЛЬКО ответы с
#РЕАЛЬНЫМИ числами.
#Место ОДНО: внутри программы работает этот же серверный код на 127.0.0.1 (десктопный
#`vector/engine.py`, с которым набор когда-то надо было сверять, удалён 15.08.2026). Когда
#мест было два, на вебе набор забыли перенести — отсюда был баг с плейсхолдерами на сайте.
#intent → LLM НЕ вызываем (нет цифр для переформулировки ИЛИ формат нельзя ломать):
#  hello/thanks/help/unknown — текст-справка без чисел (иначе модель дописывает
#    плейсхолдеры «[укажите средние баллы]» вместо фактов, см. §5);
#  about_* — статичные факты о заведении;
#  schedule — структурный список пар: LLM мог бы добавить/выкинуть занятие.
#  weather — реальные показания метеослужбы: модель, «озвучивая данные», охотно
#            меняет числа, а неверная температура в продукте, обещающем не врать,
#            дороже красивой формулировки.
#  homework — текст задания написал ПРЕПОДАВАТЕЛЬ, и человек должен прочитать его
#             дословно; перефразированная домашка это уже другая домашка.
#  server_state — одни числа (диск, память, размер базы): модель их округляет и меняет
#             единицы, а по этим цифрам принимают решения.
_NO_VOICE_INTENTS = {"hello", "thanks", "help", "unknown",
                     "about_vsgutu", "about_college", "schedule", "weather", "howto",
                     "homework", "server_state"}


def _names_a_person(text: str, db: Session) -> bool:
    """Есть ли в тексте фамилия ЛЮБОГО человека из справочника (студент, сотрудник,
    родитель). Одна дверь для «можно ли отдать этот текст модели» — и для вопроса, и для
    перевода готового ответа. Сравнение по основе фамилии (`vector_nlu.match_surname`):
    ложное срабатывание стоит лишь озвучки, пропуск — ФИО у внешнего сервиса."""
    if not text:
        return False
    try:
        rows = db.query(User.surname).filter(User.deleted == False).distinct().all()  # noqa: E712
    except Exception:      # noqa: BLE001 — не смогли проверить: считаем, что имя есть
        return True
    surnames = [r[0] for r in rows if r[0] and len(r[0].strip()) >= 3]
    return bool(vector_nlu.match_surname(text, surnames))


def _active_children(db: Session, parent: User) -> list:
    """Дети, чья привязка к родителю ПОДТВЕРЖДЕНА студентом (инвариант §4.13)."""
    from ...models import ParentLink
    ids = [r.student_id for r in db.query(ParentLink).filter(
        ParentLink.parent_id == parent.id, ParentLink.status == "active").all()]
    if not ids:
        return []
    return (db.query(User).filter(User.id.in_(ids), User.role == "student",
                                  User.deleted == False).all())  # noqa: E712


#Ответы студенту написаны на «ты» о нём самом. Родитель читает их о РЕБЁНКЕ: «Твой
#средний балл» взрослому человеку — это ошибка адресата, а не стиль (живой прогон
#01.10.2026). Таблица явная, а не «замени все „твой“»: так видно, какие фразы покрыты, и
#новая фраза без пары не испортит соседнюю. Держит test_vector_surnames.py.
_PARENT_VOICE = (
    ("Задолженностей нет — так держать! 🐯", "Задолженностей нет. 🐯"),
    ("Всего у тебя оценок —", "Всего у ребёнка оценок —"),
    ("у тебя пока нет занятий с оценками", "у ребёнка пока нет занятий с оценками"),
    ("Предметы за твоей группой пока не закреплены", "Предметы за группой ребёнка пока не закреплены"),
    ("Твои предметы (", "Предметы ребёнка ("),
    ("Твой средний по предметам:", "Средний ребёнка по предметам:"),
    ("Твой средний балл —", "Средний балл ребёнка —"),
    ("Я могу показать твой средний балл", "Я могу показать средний балл ребёнка"),
    ("Твоя группа —", "Группа ребёнка —"),
    ("Группа за тобой не закреплена.", "Группа за ребёнком не закреплена."),
    ("ЗЕТ по твоим предметам", "ЗЕТ по предметам ребёнка"),
)


def _to_parent_voice(text: str) -> str:
    for old, new in _PARENT_VOICE:
        text = text.replace(old, new)
    return text


def user_ui_locale(user: User) -> str:
    """Язык интерфейса ЭТОГО пользователя ('ru', если перевод выключен/не выбран).

    ⚠️ Вызывать на СВОЁМ `user` того, кто спрашивает, а не на чужой записи — в
    `parent.py` это родитель, а не ребёнок, чьими данными отвечает Вектор (см.
    `parent_vector_ask`): иначе Вектор заговорил бы на языке, который родитель не выбирал."""
    prefs = user.prefs or {}
    return (prefs.get("locale") or "ru") if prefs.get("locale_on") else "ru"


def answer_vector_question(question: str, user: User, db: Session, context: str = "",
                           voice_role: str = "", locale: str = "ru", addressee=None) -> dict:
    """Общая логика ответа Вектора (вынесена из `vector_ask`, чтобы её мог переиспользовать
    мессенджер — команда `/vector <вопрос>` в любом чате, см. `routers/messenger.py`).
    Тот же принцип, что в десктопе: цифры берутся из реальных данных (SQL) — модель их НЕ
    выдумывает. Фактический текст собирает `_vector_facts`, затем LLM-провайдер
    (GigaChat/Ollama/оффлайн — из СИНХРОНИЗИРОВАННОГО конфига админа) лишь ПЕРЕФОРМУЛИРУЕТ
    его в стиле Вектора. Роль вызывающего (`user.role`) скоупит данные, как и в дедике.

    `locale` — язык ИНТЕРФЕЙСА вызывающего (см. `user_ui_locale`), не факт данных: цифры
    и ФИО остаются теми же, меняется только язык вокруг них (§ролей, полный перевод)."""
    cfg = W.load_config(db)
    #🔥 РОДИТЕЛЬ В ОБЩЕЙ ДВЕРИ (01.10.2026, живой прогон). Кабинет родителя спрашивает
    #своей ручкой с номером ребёнка, а команда `/vector` в мессенджере и общая ручка
    #приходили сюда с записью САМОГО родителя — и роль молча считалась студенческой:
    #«Твой средний балл — 0.0», «Задолженностей нет — так держать!» родителю должника.
    #Это не «нет данных», а ложь о ребёнке. Отвечаем данными ребёнка, если он один и
    #согласие дано; иначе — объясняем, где спросить.
    if user.role == "parent" and voice_role != "parent":
        kids = _active_children(db, user)
        if len(kids) == 1:
            return answer_vector_question(question, kids[0], db, context, voice_role="parent",
                                          locale=locale, addressee=user)
        text = ("Доступ к журналу ребёнка откроется, когда студент подтвердит привязку в своём "
                "кабинете. 🐯" if not kids else
                "У вас несколько детей — откройте «ИИ Помощник» в разделе ребёнка, и я отвечу "
                "по его журналу. 🐯")
        return {"text": text, "mood": "neutral", "intent": "help", "facts": {}}
    #`addressee` — кто ЧИТАЕТ ответ, если данные чужие: родитель спрашивает данными ребёнка,
    #но «Здравствуйте, <имя>» и справка обязаны быть про родителя, а не про ребёнка.
    result = _vector_facts(question.lower(), user, db, cfg, addressee=addressee)
    intent = result.get("intent")
    if voice_role == "parent" and intent in ("hello", "help"):
        result["text"] = (_hello_text(addressee, "parent") if intent == "hello"
                          else _HELP_BY_ROLE["parent"])
    elif voice_role == "parent":
        result["text"] = _to_parent_voice(result.get("text", ""))
    #🔒 ФАМИЛИЯ В САМОМ ВОПРОСЕ = В МОДЕЛЬ НЕ ИДЁТ НИЧЕГО (возражение Полковника
    #29.09.2026). `vector_llm.voice` и `free_chat` кладут вопрос в промпт ДОСЛОВНО, и
    #«ЗЕТ Иванова» отдавал фамилию наружу при совершенно чистом тексте ответа — у
    #сотрудника, у студента и у родителя одинаково. Одна дверь для всех ролей и всех
    #входов (сайт, программа, мессенджер, кабинет родителя), а не флаг в каждом
    #обработчике. Держит `test_vector_never_voices_names.py`: шпион видит и вопрос.
    named = _names_a_person(question, db)
    if named:
        result["no_voice"] = True
    #voice_role меняет ТОЛЬКО тон обращения, но не скоуп данных. Нужен кабинету родителя:
    #факты там собираются от лица РЕБЁНКА (иначе пришлось бы дублировать весь студенческий
    #скоуп и однажды разойтись с ним), а говорить «твой средний балл» родителю — странно.
    role = voice_role or user.role
    #Вопрос НЕ из пула (unknown) — свободный small-talk: пара фраз + мягкий возврат к учёбе,
    #без решения задач (см. vector_llm.free_chat). Данные журнала тут не выдумываем.
    if intent == "unknown":
        #context — обезличенные заметки из «Избранного» (пусто для обычного /web/vector/ask):
        #помогает понять «а это когда?», но цифры успеваемости из него брать запрещено.
        #Названо ФИО — болтать с моделью нельзя (вопрос уйдёт ей дословно): офлайн-ответ.
        result["text"] = (vector_llm.offline_reply(role, locale) if named
                          else vector_llm.free_chat(cfg, question, role, context, locale))
    #Озвучка: числа уже посчитаны и верны, LLM их не трогает — только стиль (и, если выбран
    #другой язык интерфейса, ЯЗЫК ответа — persona получает инструкцию, см. vector_llm).
    #Оффлайн или ошибка провайдера → вернётся исходный фактический текст (сайт не ломается).
    #Приветствие/справку/благодарность/расписание НЕ озвучиваем (см. _NO_VOICE_INTENTS).
    elif intent not in _NO_VOICE_INTENTS and not result.get("no_voice"):
        #no_voice — ответ содержит фактический список (имена, причины), который LLM исказил
        #бы или отказался озвучивать. Отдаём как есть.
        result["text"] = vector_llm.voice(cfg, result.get("text", ""), role, question, locale)
    elif locale != "ru":
        #Не озвучиваемый (структурный/фактический) ответ всё равно должен быть на выбранном
        #языке. Без данных (hello/thanks/help/about_*/howto) — готовый ручной перевод;
        #с реальными данными (расписание/погода/домашка/сервер/списки) — перевод ГОТОВОГО
        #русского текста постфактум, факты при этом не пересчитываются.
        role_for_static = ("parent" if voice_role == "parent" else user.role
                           if user.role in ("student", "teacher", "admin", "moderator")
                           else "student")
        if intent in _STATIC_TEXT_INTENTS:
            _localize_static(result, role_for_static, locale, addressee or user)
        elif not _names_a_person(result.get("text", ""), db):
            #🔒 Перевод моделью — только текст БЕЗ ФИО (29.09.2026). Список группы или
            #должников на английском интерфейсе иначе уезжал бы в LLM целиком «на перевод»:
            #не озвучивается ≠ не уходит наружу. С фамилиями ответ остаётся русским.
            _localize_dynamic(result, locale, cfg)
    result.pop("no_voice", None)   #внутренний флаг наружу не отдаём
    return result


@router.post("/vector/ask")
def vector_ask(payload: dict = Body(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Серверный «Вектор» — см. `answer_vector_question`. Студент видит только свои данные."""
    question = (payload.get("message") or "").strip()
    return answer_vector_question(question, user, db, locale=user_ui_locale(user))


# ── Голосовой ввод (Speech-to-Text) — ЗАГОТОВКА, распознаёт на ХОСТЕ ────────────────
def _stt_installed() -> bool:
    """Стоит ли движок распознавания на ЭТОМ хосте (faster-whisper)."""
    try:
        from ... import stt_service
        return bool(stt_service.is_available())
    except Exception:
        return False


#Режимы голосового ввода (настройка админа `stt_mode`):
#  auto    — Whisper, если он есть на хосте; иначе распознаёт сам браузер. По умолчанию:
#            у кого локально стоит — тот и получает Whisper, никого не заставляя качать.
#  server  — ТОЛЬКО Whisper на сервере. Это «задел на продажу»: на боевом VPS движка нет
#            (1 ядро, 960 МБ — модель туда не влезает), поэтому режим честно отвечает
#            «недоступно», пока у колледжа не появится машина с видеокартой.
#  browser — ТОЛЬКО встроенное распознавание браузера, даже если Whisper установлен.
_STT_MODES = ("auto", "server", "browser")


@router.get("/vector/stt/status")
def vector_stt_status(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Каким движком распознавать речь и доступен ли он.

    Решение принимает СЕРВЕР, а не клиент: иначе десктоп и сайт разошлись бы в поведении,
    а админ не смог бы включить Whisper «для всех» одним переключателем.

    `engine`: 'whisper' — шлём аудио на `/web/vector/stt`; 'browser' — клиент распознаёт
    сам; '' — голосовой ввод недоступен, и тогда `reason` объясняет, почему именно."""
    installed = _stt_installed()
    mode = (W.load_config(db).get("stt_mode") or "auto").strip()
    if mode not in _STT_MODES:
        mode = "auto"
    if mode == "browser":
        return {"available": True, "mode": mode, "engine": "browser",
                "installed": installed, "reason": ""}
    if installed:
        return {"available": True, "mode": mode, "engine": "whisper",
                "installed": True, "reason": ""}
    if mode == "server":
        #Жёстко выбран Whisper, а его нет — молча подменять браузерным нельзя: админ
        #включил распознавание НА СЕРВЕРЕ осознанно (ПДн не должны уходить в облако
        #браузера), и тихая подмена нарушила бы именно это решение.
        return {"available": False, "mode": mode, "engine": "",
                "installed": False,
                "reason": "Распознавание на сервере включено, но движок на нём не установлен."}
    return {"available": True, "mode": mode, "engine": "browser",
            "installed": False, "reason": ""}


def _stt_context(db: Session, user: User) -> str:
    """Слова, которые модель должна ожидать: имя маскота, предметы, фамилии своих студентов.

    Это не «улучшение по вкусу»: без такой подсказки Whisper уверенно подменяет редкие
    имена похожими обычными словами, и распознанное выглядит правдоподобно — а значит
    ошибку легко не заметить. Ограничиваем список: слишком длинная подсказка размывает
    внимание модели и начинает мешать."""
    words = ["Вектор", "ВСГУТУ"]
    try:
        cfg = W.load_config(db)
        ty, ts = W.current_term(cfg)
        if user.role == "teacher":
            pairs = W.teacher_assignments(db, user.id, ty, ts)
            words += sorted({s for _g, s in pairs})[:12]
            for group in sorted({g for g, _s in pairs})[:4]:
                words += [st.surname for st in W.students_in_group(db, group)][:30]
        elif user.role == "student":
            #Раньше здесь стояла защита hasattr(W, "_group_subject_list") на функцию,
            #которой в webdata никогда не существовало — то есть ветка не срабатывала
            #НИ РАЗУ, и студент молча оставался без подсказки с названиями предметов.
            words += W.group_subject_list(db, user.group_name or "")[:12]
    except Exception:
        pass
    #Уникальные, порядок сохраняем: первым идёт то, что важнее узнать.
    seen, out = set(), []
    for w in words:
        w = (w or "").strip()
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return ", ".join(out[:60])


@router.post("/vector/voice/command")
def vector_voice_command(payload: dict = Body(...),
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Разобрать РАСПОЗНАННУЮ фразу преподавателя в НАМЕРЕНИЕ (оценки / занятие / вопрос).

    ⚠️ ЭТОТ ЭНДПОИНТ НИЧЕГО НЕ ПИШЕТ. Он только предлагает — запись выполняет уже
    существующий `POST /web/teacher/grade` после того, как преподаватель подтвердил
    список в диалоге. Отдельного «голосового» пути записи НЕТ намеренно: второй путь
    означал бы вторую проверку прав и второй формат ключа оценки, а именно из-за
    расползания таких копий ключи оценок когда-то собирались в семи местах.

    LLM в цепочке НЕ участвует: разбор детерминированный (общий модуль `voice_command.py`,
    тот же, что на десктопе). Модель ошибается молча, а оценка не тому студенту — худшее,
    что может сделать журнал.

    Роль-скоуп обычный: только преподаватель и только своя группа+предмет.
    """
    _require("teacher", user)
    text = (payload.get("text") or "").strip()
    group = (payload.get("group") or "").strip()
    subject = (payload.get("subject") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустая фраза")
    if not (group and subject):
        raise HTTPException(status_code=400, detail="Нужны группа и предмет")

    cfg = W.load_config(db)
    ty, ts = W.current_term(cfg)
    #Право на ЭТУ группу и ЭТОТ предмет — до любого разбора: подсказывать состав чужой
    #группы (а ростер уходит в подсказку распознавателя) мы не имеем права.
    _teacher_check_assignment(db, user, group, subject, ty, ts)

    students = W.students_in_group(db, group)
    roster = [(st.surname or "", st.name or "") for st in students]

    #Занятия ЗА СЕГОДНЯ по этому предмету — к ним привяжутся оценки. Дата в базе хранится
    #как ДД.ММ.ГГГГ (формат десктопа), поэтому сравниваем строкой в том же виде.
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y")
    todays = [{"id": l.id, "label": f"{l.type} №{l.number}"}
              for l in db.query(Lesson).filter(
                  Lesson.group_name == group, Lesson.subject == subject,
                  Lesson.date == today, Lesson.year == ty, Lesson.semester == ts,
                  Lesson.deleted == False).all()]      # noqa: E712

    import voice_command
    res = voice_command.parse_batch(text, roster, todays)
    return {
        "kind": res.kind,
        "is_question": bool(res.is_question),
        "heard": res.heard,
        "error": res.error,
        "warnings": list(res.warnings),
        "lesson_id": res.lesson_id,
        "lesson_label": res.lesson_label,
        #Плоский список правок — ровно в том виде, в котором клиент затем отправит их в
        #`/web/teacher/grade` (surname/name/grade). Ничего додумывать ему не придётся.
        "items": [{"surname": i.surname, "name": i.name, "who": i.who,
                   "action": i.action, "grade": i.value} for i in res.items],
        "lesson": ({"type": res.lesson.type, "topic": res.lesson.topic,
                    "number": res.lesson.number} if res.lesson else None),
    }


@router.post("/vector/stt")
async def vector_stt(file: UploadFile = File(...),
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Принимает аудио (getUserMedia/MediaRecorder из браузера), распознаёт на ХОСТЕ и
    возвращает текст. Клиент дальше сам решает: вопрос → /web/vector/ask, а команду
    записи (для преподавателя) — через подтверждение (как в десктопе). Здесь только STT."""
    from ... import stt_service
    if not stt_service.is_available():
        raise HTTPException(status_code=503,
                            detail="Голосовой ввод не настроен на сервере.")
    #Уважаем выбор админа: при режиме «распознаёт браузер» серверный движок не работает,
    #даже если установлен. Иначе настройка была бы декоративной — устаревший клиент
    #продолжал бы грузить хост, хотя администратор это запретил.
    if (W.load_config(db).get("stt_mode") or "auto").strip() == "browser":
        raise HTTPException(status_code=503,
                            detail="Распознавание на сервере отключено администратором.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Пустой аудиофайл.")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Аудио слишком большое (макс 10 МБ).")
    cfg = W.load_config(db)
    #🎯 ПОДСКАЗКА МОДЕЛИ — то, чего здесь не хватало, и из-за чего «Вектор» слышался как
    #«Виктор», а фамилии студентов превращались в похожие русские слова. Нативная версия
    #подсказку давала, серверная — нет, поэтому качество на вебе было заметно хуже при
    #той же модели. Whisper опирается на контекст: список ожидаемых слов резко поднимает
    #узнавание редких имён (бурятские ФИО — Самбуева, Гындынова, Баянжаргал).
    #Скоуп ролевой, как везде: студент подсказывает свои предметы, преподаватель — ещё и
    #фамилии своих студентов. Чужих ФИО в подсказку не попадает.
    #⚠️ РАСПОЗНАВАНИЕ УХОДИТ В ПОТОК, И ЭТО НЕ ОПТИМИЗАЦИЯ, А ИСПРАВЛЕНИЕ ОТКАЗА.
    #Эндпоинт объявлен `async def` (иначе не прочитать файл через `await file.read()`),
    #а `transcribe_bytes` — обычная синхронная функция, которая считает Whisper'ом
    #секунды, а на большой модели и десятки секунд. Прямой вызов замораживал ЕДИНСТВЕННЫЙ
    #цикл событий: на всё это время вставали и мессенджер, и веб-сокеты, и `/health` —
    #то есть один человек, надиктовавший оценку, останавливал сервер всему колледжу.
    #Соседние 150 ручек мессенджера объявлены обычным `def`, и FastAPI уводит их в пул
    #потоков сам; здесь этот путь закрыт формой эндпоинта, поэтому поток берём явно.
    res = await run_in_threadpool(
        stt_service.transcribe_bytes,
        data, filename=file.filename or "audio.webm",
        size=cfg.get("stt_model", "large-v3"), device=cfg.get("stt_device", "auto"),
        context=_stt_context(db, user))
    if not res["ok"]:
        raise HTTPException(status_code=500, detail=res["error"])
    return {"text": res["text"]}


# ── Голосовая ОЗВУЧКА (Text-to-Speech) — синтез на ХОСТЕ (Silero), см. tts_service ──
@router.get("/vector/tts/status")
def vector_tts_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Доступна ли озвучка: движок стоит на хосте И админ её не выключил. По этому флагу
    и списку голосов веб-клиент решает, показывать ли кнопку динамика и выбор голоса."""
    from ... import tts_service
    cfg = W.load_config(db)
    enabled = cfg.get("tts_enabled", True)
    return {"available": bool(enabled) and tts_service.is_available(),
            "voices": tts_service.voices()}


@router.post("/vector/tts")
def vector_tts(payload: dict = Body(...),
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Синтезирует переданный текст (уже готовый ответ Вектора, без ПДн) в WAV. Голос
    (male/female) выбирает пользователь в настройках. Кэш — внутри tts_service."""
    from fastapi.responses import Response
    from ... import tts_service
    cfg = W.load_config(db)
    if not cfg.get("tts_enabled", True):
        raise HTTPException(status_code=503, detail="Озвучка отключена администратором.")
    text = (payload.get("text") or "").strip()
    voice = (payload.get("voice") or "male").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Пустой текст.")
    #Движок синтеза выбирается конфигом (silero сейчас; клон-голос на GPU — потом).
    res = tts_service.synthesize(text, voice, engine=cfg.get("tts_engine", "silero"))
    if not res["ok"]:
        #Движок не поднялся / нет модели — 503: клиент откатится на speechSynthesis.
        raise HTTPException(status_code=503, detail=res["error"])
    return Response(content=res["audio"], media_type=res["mime"],
                   headers={"Cache-Control": "no-store"})


#Слова-триггеры «что умеешь / помощь / кто ты» и приветствие — распознаём ПЕРВЫМИ,
#чтобы Вектор отвечал по делу, а не сваливался в статистику. Дефолт тоже = подсказка.
# Факты о заведении — источник правды, НЕ генерация (как vector/knowledge.py на десктопе).
#Факты о заведении. Держать СИНХРОННО с vector/knowledge.py (ANSWER_VSGUTU/ANSWER_COLLEGE)
#— это источник правды десктопа (§12). Импортировать оттуда напрямую нельзя: vector/__init__
#тянет десктопные engine/intents, и на сервере это падает. Поэтому — копия с пометкой,
#как и другие «обязаны совпадать» дубли (_NO_VOICE_INTENTS, grade_id). Раньше сервер нёс
#УРЕЗАННУЮ версию (без истории и масштаба) и расходился с десктопом.
_ABOUT_VSGUTU = (
    "ВСГУТУ — это Восточно-Сибирский государственный университет технологий и "
    "управления в Улан-Удэ (Республика Бурятия). Основан 19 июня 1962 года как "
    "Восточно-Сибирский технологический институт (ВСТИ); в 1994 году получил статус "
    "университета, а в 2011-м переименован во ВСГУТУ. Сегодня это один из крупнейших "
    "вузов Сибири и Дальнего Востока — свыше 15 тысяч студентов и более 1900 "
    "преподавателей и сотрудников. Основной адрес — ул. Ключевская, 40В."
)
_ABOUT_COLLEGE = (
    "Технологический колледж ВСГУТУ — структурное подразделение университета в "
    "Улан-Удэ, которое даёт среднее профессиональное образование (СПО) и готовит "
    "специалистов среднего звена. После колледжа можно продолжить учёбу в самом "
    "ВСГУТУ. Группы колледжа обозначаются буквой «К» (например, К75/1). Этот "
    "электронный журнал — внутренняя система колледжа: оценки, посещаемость, "
    "пересдачи и успеваемость по группам."
)

def _howto_text(cfg: dict, role: str = "student") -> str:
    """Справка «как устроено». Правило среднего — из НАСТРОЙКИ (`grading.methodology_text`).

    ⚠️ До 28.09.2026 здесь было зашито «средний считается по практикам и экзаменам», а
    ответ на «мой средний балл» тут же писал «экзамены НЕ входят в средний» — входят ли
    экзамены, решает настройка администратора (`avg_include_exam`), и справка обязана
    говорить то же, что расчёт. Там же «зона риска — средний ниже 3»: дашборды и Вектор
    считают её по индексу риска отчисления (`W.counts_as_at_risk`)."""
    ask = "Спроси" if role == "student" else "Спросите"
    return ("Как всё устроено в журнале:\n"
            "• " + W.grading.methodology_text(cfg) + " Пересдача заменяет прежнюю "
            "попытку — учитывается последняя.\n"
            "• Задолженность — несданная практика или ДЗ (2 или Н) либо незачтённый экзамен.\n"
            "• Посещаемость: Н — неявка, Б — по болезни, О — опоздание (был на занятии, в "
            "пропуски не идёт).\n"
            "• Зона риска — студенты со средним или высоким риском отчисления: индекс "
            "складывается из среднего балла, долгов и пропусков, тот же, что на дашбордах "
            "преподавателя и куратора.\n"
            f"{ask} про цифры словами — я беру их из реальных данных, а не выдумываю.")


#⚠️ Обращение держим ОДНО на роль: студенту — «ты», остальным — «вы». До 28.09.2026 в
#справке преподавателя было «Здравствуйте!» и тут же «твоих групп… Спрашивай» — два
#регистра в одном сообщении (находка живого прогона). Примеры вопросов — только те, на
#которые у роли ДЕЙСТВИТЕЛЬНО есть ответ: админская справка обещала «сводку по группе
#<название>», которая отвечала общим счётчиком колледжа.
_HELP_BY_ROLE = {
    "student": ("Я — Вектор 🐯, помогаю с учёбой по твоим РЕАЛЬНЫМ данным (цифры не выдумываю). "
                "Спроси словами: «мой средний балл», «сколько у меня оценок», «оценки по "
                "информатике», «есть ли долги», «сколько пропусков», «когда математика», "
                "«что завтра». Или жми кнопки под чатом."),
    "teacher": ("Я — Вектор 🐯, считаю строго по журналу ваших групп — тех, где вы ведёте "
                "предметы, и тех, что курируете. Умею: «сводка по группам», «кто в зоне "
                "риска», «у кого долги», «студенты К74/1», «пропуски у <фамилия>», «что "
                "задали», «расписание на завтра». Спрашивайте, как удобно."),
    "admin":   ("Я — Вектор 🐯 для администратора, считаю по всему колледжу. Умею: "
                "«сводка по колледжу», «сводка по группе К74/1», «студенты К74/1», «должники», "
                "«зона риска», «пропуски К74/1», «<фамилия студента>», «преподаватели», "
                "«расписание К74/1 на завтра», «что с сервером». Спрашивайте, как удобно."),
    "moderator": ("Я — Вектор 🐯. Модератору покажу расписание любой группы («расписание "
                  "К74/1 на завтра») и преподавателей по расписанию портала, расскажу о "
                  "колледже. Оценки и пропуски видят преподаватели и администрация."),
    "parent":  ("Я — Вектор 🐯. Расскажу об успеваемости вашего ребёнка по реальным данным "
                "журнала: «средний балл», «оценки», «долги», «пропуски», «что задали», "
                "«расписание на завтра»."),
}
_HELLO_PREFIX = {"student": "Привет", "teacher": "Здравствуйте", "admin": "Здравствуйте",
                 "moderator": "Здравствуйте", "parent": "Здравствуйте"}
_THANKS_TEXT = "Всегда рад помочь! 🐯"
_SCHED_DAYS = ["Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт"]


# ── Полный перевод интерфейса: локализация ответов Вектора ─────────────────────────
# Интенты БЕЗ данных (hello/thanks/help/about_*/howto) переведены вручную и один раз —
# ни числа, ни ФИО в них не участвуют, поэтому это ровно тот случай, где ручной перевод
# надёжнее и мгновеннее LLM (см. dictionaries.js на фронте — тот же принцип). Всё
# ОСТАЛЬНОЕ, что не озвучивается (`_NO_VOICE_INTENTS`/`no_voice=True` — расписание,
# погода, домашка, состояние сервера, списки должников), — реальные данные, вторую
# ручную копию для них на 3 языка не пишем, а прогоняем ГОТОВЫЙ русский текст через
# LLM-перевод постфактум (`_localize_dynamic`) — числа/ФИО от этого не меняются, меняется
# только язык вокруг них. Нет LLM/сбой перевода → тихо остаётся русский текст.
_STATIC_TEXT_INTENTS = {"hello", "thanks", "help", "about_vsgutu", "about_college", "howto"}

_STATIC_TEXT = {
    "en": {
        "about_vsgutu": (
            "ESSTU is the East Siberia State University of Technology and Management in "
            "Ulan-Ude (Republic of Buryatia, Russia). Founded on June 19, 1962 as the East "
            "Siberian Technological Institute; it became a university in 1994 and was "
            "renamed ESSTU in 2011. Today it's one of the largest universities in Siberia "
            "and the Russian Far East — over 15,000 students and more than 1,900 faculty "
            "and staff. Main address: 40V Klyuchevskaya St."
        ),
        "about_college": (
            "The ESSTU Technological College is a structural unit of the university in "
            "Ulan-Ude that provides vocational secondary education and trains mid-level "
            "specialists. After college, you can continue studying at ESSTU itself. "
            "College groups are labeled with the letter «К» (e.g., К75/1). This "
            "gradebook is the college's internal system: grades, attendance, resits and "
            "performance by group."
        ),
        "howto": (
            "How the gradebook works:\n"
            "• The average is calculated from practicals and homework (lectures aren't "
            "counted); whether exams count is set by the administration. A retake replaces "
            "the previous attempt — only the latest one counts.\n"
            "• A debt is an unpassed practical (a 2 or an absence) or a failed exam.\n"
            "• Attendance: Н — absent, Б — sick leave, О — late (the student was present; "
            "not counted as an absence).\n"
            "• The risk zone: students with a medium or high dropout-risk index, which "
            "combines the average, debts and absences — the same index as on the "
            "teacher and curator dashboards.\n"
            "Ask about your numbers in plain words — I pull them from real data, I don't "
            "make them up."
        ),
        "help_by_role": {
            "student": ("I'm Vector 🐯, I help with your studies using your REAL data (I "
                        "never make numbers up). Ask in plain words: “my average”, "
                        "“how many grades do I have”, “grades in computer "
                        "science”, “do I have any debts”, “how many "
                        "absences”, “when is math”, “what's "
                        "tomorrow”. Or use the buttons under the chat."),
            "teacher": ("I'm Vector 🐯 — I count strictly from the gradebook of your groups: "
                        "the ones you teach and the ones you supervise. Ask: “summary by "
                        "group”, “who's at risk”, “who has debts”, “students "
                        "К74/1”, “absences for <surname>”, “homework”, "
                        "“tomorrow's schedule”."),
            "admin": ("I'm Vector 🐯 for administrators — I count across the whole college. "
                      "Ask: “college summary”, “summary for group К74/1”, “students "
                      "К74/1”, “debtors”, “risk zone”, “absences К74/1”, "
                      "“<student surname>”, “teachers”, “schedule К74/1 "
                      "tomorrow”, “server status”."),
            "moderator": ("I'm Vector 🐯. For moderators I can show any group's schedule "
                          "(“schedule К74/1 tomorrow”) and teachers from the portal "
                          "schedule, and tell you about the college. Grades and absences are "
                          "visible to teachers and the administration."),
            "parent": ("I'm Vector 🐯. I'll tell you how your child is doing using real "
                       "gradebook data: “average”, “grades”, “debts”, “absences”, "
                       "“homework”, “tomorrow's schedule”."),
        },
        "hello_prefix": {"student": "Hi", "teacher": "Hello", "admin": "Hello",
                         "moderator": "Hello", "parent": "Hello"},
        "thanks": "Always happy to help! 🐯",
    },
    "zh": {
        "about_vsgutu": (
            "东西伯利亚国立技术大学（ESSTU）位于俄罗斯布里亚特共和国乌兰乌德市。始建于1962年6月19日，"
            "最初名为东西伯利亚技术学院；1994年升格为大学，2011年更名为ESSTU。如今它是西伯利亚和俄罗斯"
            "远东地区最大的高校之一——在校学生超过15000人，教职工超过1900人。主校区地址：Ключевская街40В号。"
        ),
        "about_college": (
            "ESSTU技术学院是该大学设在乌兰乌德的一个下属机构，提供中等职业教育，培养中级专业人才。"
            "从学院毕业后可以继续在ESSTU本部深造。学院班级以字母“К”标注（例如К75/1）。"
            "这个电子成绩册就是学院的内部系统：成绩、出勤、补考和各班级的学习情况。"
        ),
        "howto": (
            "成绩册的工作原理：\n"
            "• 平均分根据平时成绩和作业计算（不包括讲座）；考试是否计入由管理部门设定。补考会替换之前的成绩——只计最新一次。\n"
            "• 欠考是指未通过的平时作业（得2分或缺勤）或未通过的考试。\n"
            "• 出勤情况：Н——缺勤，Б——病假，О——迟到（学生到过课，不计入缺勤）。\n"
            "• 高危学生：退学风险指数为中或高的学生，指数综合平均分、欠考和缺勤，与教师和班主任面板相同。\n"
            "用你自己的话问我关于你的数据——我从真实数据中获取，不会编造。"
        ),
        "help_by_role": {
            "student": ("我是维克托🐯，会根据你的真实数据帮你学习（绝不编造数字）。用自己的话问我："
                        "「我的平均分」「我有多少个成绩」「计算机课的成绩」「我有欠考吗」"
                        "「我缺勤了几次」「数学课什么时候」「明天有什么课」。也可以点击聊天下方的按钮。"),
            "teacher": ("我是维克托🐯，严格按照您所带班级（授课和担任班主任的班级）的成绩册计算。"
                        "可以问：「各班汇总」「谁处于高危」「谁有欠考」「К74/1的学生」"
                        "「<姓氏>的缺勤」「布置了什么作业」「明天的课表」。"),
            "admin": ("我是维克托🐯，为管理员服务，按全院数据计算。可以问：「全院汇总」"
                      "「К74/1班汇总」「К74/1的学生」「欠考学生」「高危学生」「К74/1的缺勤」"
                      "「<学生姓氏>」「教师名单」「К74/1明天的课表」「服务器状态」。"),
            "moderator": ("我是维克托🐯。我可以为版主显示任何班级的课表（「К74/1明天的课表」）"
                          "和门户课表中的教师，并介绍学院情况。成绩和缺勤只对教师和管理部门可见。"),
            "parent": ("我是维克托🐯。我会根据成绩册的真实数据告诉您孩子的学习情况："
                       "「平均分」「成绩」「欠考」「缺勤」「作业」「明天的课表」。"),
        },
        "hello_prefix": {"student": "你好", "teacher": "您好", "admin": "您好",
                         "moderator": "您好", "parent": "您好"},
        "thanks": "随时乐意帮忙！🐯",
    },
}


def _localize_static(result: dict, role_for_static: str, locale: str, who=None) -> None:
    """Подставляет готовый перевод для интентов без данных (см. `_STATIC_TEXT_INTENTS`).
    `who` — к кому обращаться в приветствии (см. `_hello_text`)."""
    pack = _STATIC_TEXT.get(locale)
    if not pack:
        return
    intent = result.get("intent")
    if intent == "hello":
        result["text"] = _hello_text(who, role_for_static, locale)
    elif intent == "help":
        result["text"] = pack["help_by_role"][role_for_static]
    elif intent == "thanks":
        result["text"] = pack["thanks"]
    elif intent in ("about_vsgutu", "about_college", "howto"):
        result["text"] = pack[intent]


def _localize_dynamic(result: dict, locale: str, cfg: dict) -> None:
    """Переводит ГОТОВЫЙ русский ответ с реальными данными (расписание/погода/домашка/
    состояние сервера/списки должников) через тот же LLM-примитив, что и переводчик
    сообщений (`vector_llm.complete`) — вторую ручную копию на 3 языка для десятков
    комбинаций данных не пишем. Числа/ФИО/markdown модель НЕ обязана менять — только язык.
    Нет провайдера или ошибка → молча остаётся русский текст (та же деградация, что и у
    переводчика сообщений при недоступной модели)."""
    text = result.get("text")
    if not text or locale not in _LANG_NAMES:
        return
    prompt = [
        {"role": "system", "content": (
            f"Переведи следующий текст на {_LANG_NAMES[locale]} язык. Verbatim: верни "
            "ТОЛЬКО перевод, без кавычек и пояснений. Сохрани числа, даты, имена, "
            "маркированные списки (•), переносы строк и эмодзи как есть.")},
        {"role": "user", "content": text},
    ]
    try:
        out = (vector_llm.complete(cfg, prompt, temperature=0.1) or "").strip()
    except Exception:
        out = ""
    if out:
        result["text"] = out


#Те же коды/названия языков, что у переводчика сообщений (translate_service.LANGUAGES) —
#не заводим вторую копию, иначе однажды разойдутся списки поддерживаемых языков.
_LANG_NAMES = {k: v for k, v in translate_service.LANGUAGES.items() if k != "ru"}


def _known_subjects(user: User, db: Session) -> list:
    """Предметы в области видимости пользователя (для распознавания «по информатике»).
    Студент — предметы занятий своей группы; преподаватель — свои; админ — все."""
    try:
        if user.role == "student":
            #Не только из занятий: предмет из импортированного учебного плана существует
            #в Group.subjects ещё до того, как по нему заведут первое занятие — иначе
            #«оценки по <предмету>» не распознавали бы сам предмет (см. group_subject_list).
            return W.group_subject_list(db, user.group_name or "")
        if user.role == "teacher":
            ty, ts = W.current_term(W.load_config(db))
            out = {s for _g, s in W.teacher_assignments(db, user.id, ty, ts)}
            #Курируемые группы — та же область видимости, что у `_teacher_facts`: куратор,
            #не ведущий в своей группе ни одного предмета, спрашивает именно про её
            #предметы, и без них «оценки Иванова по физике» не опознавали бы предмет.
            for g in user.curated_groups or []:
                out.update(W.group_subject_list(db, g))
            return sorted(out)
        rows = db.query(Subject.name).filter(Subject.deleted == False).all()  # noqa: E712
        return sorted({r[0] for r in rows if r[0]})
    except Exception:
        return []


def _known_surnames(user: User, db: Session) -> list:
    """Фамилии студентов в области видимости (для «пропуски у Иванова»). Студенту —
    пусто (только о себе); преподавателю — студенты групп по нагрузке И курируемых;
    админу — все студенты.

    ⚠️ Область обязана совпадать с `_teacher_facts` (нагрузка ∪ кураторство). Здесь стояла
    только нагрузка (ревью 30.09.2026): куратор без предметов в своей группе спрашивал
    «пропуски у Иванова», фамилия не опознавалась, и вместо карточки студента приходил
    общий ответ — при том что права на эти данные у него есть."""
    if user.role == "student":
        #Своя фамилия — чтобы «оценки Хандакова», спрошенное самим Хандаковым, было
        #вопросом о себе, а не непонятой фразой (живой прогон 01.10.2026). Чужие фамилии
        #студенту не нужны: вопрос о другом человеке опознаётся отдельно и получает отказ
        #(см. `_outside_scope_answer`).
        return [user.surname] if user.surname else []
    try:
        if user.role == "teacher":
            ty, ts = W.current_term(W.load_config(db))
            out = []
            groups = set(W.teacher_group_names(db, user.id, ty, ts)) | set(user.curated_groups or [])
            for g in sorted(groups):
                out += [s.surname for s in W.students_in_group(db, g)]
            return sorted(set(out))
        rows = db.query(User.surname).filter(User.role == "student",
                                             User.deleted == False).all()  # noqa: E712
        return sorted({r[0] for r in rows if r[0]})
    except Exception:
        return []


def _grade_breakdown(lessons, records, scale=None) -> dict:
    """Счёт оценок студента: всего практических оценок (2–5) и разбивка по баллам.
    scale — {lesson_id: шкала}/строка/None (§ролей, 3.3.1): сырое значение переводится
    в 5-балльное ПЕРЕД подсчётом, поэтому «пятёрка» на 100-балльной (90+) тоже считается."""
    counts = {"5": 0, "4": 0, "3": 0, "2": 0}
    ids = {l.id for l in lessons if l.type == "Практика"}
    scale_map = scale if isinstance(scale, dict) else None
    for lid, v in (records or {}).items():
        if lid not in ids or not v:
            continue
        lscale = scale_map.get(lid, W.grading.DEFAULT_SCALE) if scale_map is not None else (scale or W.grading.DEFAULT_SCALE)
        num = W.grading.to_five_point(v, lscale)
        key = str(int(num)) if num is not None else None
        if key in counts:
            counts[key] += 1
    counts["всего"] = sum(counts[k] for k in ("5", "4", "3", "2"))
    return counts


def _zet_facts(db, surname: str, name: str, group: str, cfg: dict,
               student_id: str | None = None, who: str = "") -> dict:
    """Вектор: «Сколько у меня ЗЕТ / хватит ли для перевода» (docs/done/PLAN-ZET.md §6).
    Факты — из того же расчёта, что и /web/student/zet; LLM (если подключена) только
    переформулирует, порог и цифры не выдумывает.

    `who` — сотрудник спрашивает о СТУДЕНТЕ («ЗЕТ Иванова»): тогда ответ называет его, а
    не «у тебя», и не озвучивается (в нём ФИО)."""
    ty, ts = W.current_term(cfg)
    summ = W.zet_summary_for_student(db, surname, name, group, ty, ts, student_id=student_id)
    if not summ["subjects"]:
        return {"text": (f"{who}: ЗЕТ по предметам пока не заданы администрацией." if who
                         else "ЗЕТ по твоим предметам пока не заданы администрацией."),
                "mood": "neutral", "intent": "zet", "facts": {}, "no_voice": bool(who)}
    threshold = db.get(ZetThreshold, zet_threshold_id(group, ty, ts))
    min_zet = threshold.min_zet if (threshold and not threshold.deleted) else None
    # «Не сдано» — только ПРОВАЛЕННЫЕ (failed). Идущие предметы (pending) — это «ожидается»,
    # а не «не сдано»: назвать идущий предмет несданным — ровно то заблуждение, из-за
    # которого завели вариант C (ЗЕТ «в процессе» до рубежа семестра).
    unsatisfied = [s["subject"] for s in summ["subjects"] if s.get("state") == "failed"]
    pending_val = summ.get("pending", 0.0)
    head = f"{who}:" if who else "У тебя"
    parts = [f"{head} {summ['earned']} из {summ['total']} ЗЕТ за семестр ({summ['pct']}%)."]
    if pending_val:
        parts.append(f"Ещё {pending_val} ЗЕТ в предметах, которые ещё идут, — они "
                     f"засчитаются, когда семестр по ним завершится.")
    if min_zet is not None:
        if summ["earned"] >= min_zet:
            parts.append(f"Порог для перевода — {min_zet} ЗЕТ, он уже набран.")
        else:
            parts.append(f"Порог для перевода — {min_zet} ЗЕТ, не хватает "
                         f"{round(min_zet - summ['earned'], 1)}.")
    if unsatisfied:
        parts.append("Не сдано: " + ", ".join(unsatisfied) + ".")
    # Пока семестр идёт (есть «ожидающие» предметы), низкий баланс — не повод грустить.
    if min_zet is None or summ["earned"] >= min_zet:
        mood = "happy"
    elif summ["pct"] >= 80 or pending_val:
        mood = "neutral"
    else:
        mood = "sad"
    return {"text": " ".join(parts), "mood": mood, "intent": "zet",
            "facts": {"earned": summ["earned"], "total": summ["total"], "pct": summ["pct"],
                     "pending": pending_val, "min_zet": min_zet, "unsatisfied": unsatisfied},
            "no_voice": bool(who)}


def _subj_match(detected: str, lesson_subject: str) -> bool:
    """Совпадает ли распознанный предмет с названием из расписания (разные написания).

    Строго: ПЕРВОЕ значимое слово должно совпасть по основе + не меньше половины значимых
    слов. Иначе «коммуник» из ИКТ ложно матчит «коммуникации» в «Иностр. язык в проф.
    коммуникации» — и Вектор показывал расписание чужого предмета."""
    a, b = vector_nlu.normalize(detected), vector_nlu.normalize(lesson_subject)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    aw = [w for w in a.split() if len(w) >= 5]
    bw = [w for w in b.split() if len(w) >= 5]
    if not aw or not bw:
        return False
    first = aw[0][:6]
    if not any(w.startswith(first) for w in bw):     # первое слово обязано совпасть
        return False
    hits = sum(1 for w in aw if any(x.startswith(w[:6]) for x in bw))
    return hits >= max(1, len(aw) // 2)


def _schedule_answer(db: Session, group: str, msg: str, day) -> tuple:
    """Ответ по расписанию группы (данные — серверный парсер портала schedule_web).

    ПРЕДМЕТ ищем по предметам САМОГО расписания (портал называет их иначе, чем журнал),
    а не по журнальному списку — иначе «иностранный язык» не находился, а ложный матч по
    общему слову показывал чужой предмет. Приоритет: назван предмет → когда он; назван
    день/сегодня/завтра → пары этого дня; иначе — сегодня."""
    if not group:
        return ("Не вижу твоей группы — расписание привязано к ней. Уточни у администратора.", {})
    data = _group_schedule(db, group)   #портал + админ-правки (overlay)
    if not data or not data.get("weeks"):
        return (f"Расписание группы {group} пока не загрузилось с портала — попробуй чуть позже.", {})
    weeks = data["weeks"]
    cur_week = str(schedule_web.current_week_parity() or 1)

    def fmt(l):
        s = l.get("subject") or l.get("raw") or "занятие"
        room = f", ауд. {l['room']}" if l.get("room") else ""
        return f"{l.get('pair_no', '?')} пара ({l.get('time', '')}) — {s}{room}"

    # Все предметы, реально присутствующие в расписании этой группы (для матча запроса).
    sched_subjects = sorted({(l.get("subject") or "").strip()
                             for wk in ("1", "2")
                             for dn in _SCHED_DAYS
                             for l in weeks.get(wk, {}).get(dn, [])
                             if (l.get("subject") or "").strip()})
    subject = vector_nlu.match_subject(msg, sched_subjects) if day == "" else ""

    # A) «когда <предмет>» — ищем предмет по обеим неделям
    if subject:
        found = []
        for wk in ("1", "2"):
            for di, dname in enumerate(_SCHED_DAYS):
                for l in weeks.get(wk, {}).get(dname, []):
                    if _subj_match(subject, l.get("subject", "")):
                        wl = "" if wk == cur_week else f" ({'II' if wk == '2' else 'I'} неделя)"
                        found.append(f"{dname}, {fmt(l)}{wl}")
        if not found:
            return (f"«{subject}» в расписании группы {group} не нашёл. Возможно, предмет "
                    "называется иначе — посмотри вкладку «Расписание».", {})
        return (f"Расписание «{subject}» (группа {group}):\n• " + "\n• ".join(found),
                {"subject": subject, "count": len(found)})

    # Спросили «когда <предмет>», но предмет в расписании не опознан и день не назван —
    # не подсовываем расписание на сегодня (это ввело бы в заблуждение), а честно уточняем.
    if day == "" and "когда" in vector_nlu.normalize(msg):
        return ("Не понял, какой предмет — назови точнее (как во вкладке «Расписание»), "
                "или спроси «что сегодня» / «что завтра». 🐯", {})

    # B) конкретный день / сегодня / завтра. Берём ДАТУ целевого дня и чётность ИМЕННО
    # ЕЁ, а не сегодняшнюю: спрошенный «понедельник» в субботу — это уже СЛЕДУЮЩАЯ неделя
    # (другая чётность). Раньше брали cur_week (сегодня) → выдавали пары не той недели.
    import datetime as _dt
    today = _dt.date.today()
    today_idx = today.weekday()                # 0=Пн..6=Вс
    if day == "today":
        target = today
    elif day == "tomorrow":
        target = today + _dt.timedelta(days=1)
    elif isinstance(day, int):
        target = today + _dt.timedelta(days=(day - today_idx) % 7)   # ближайший этот день
    else:
        target = today
    idx = target.weekday()
    if idx > 5:
        return (f"В этот день у группы {group} занятий нет — выходной. 🐯", {})
    week = str(schedule_web.current_week_parity(target) or 1)         # чётность ЦЕЛЕВОГО дня
    dname = _SCHED_DAYS[idx]
    label = {"today": "Сегодня", "tomorrow": "Завтра"}.get(day, dname)
    lessons_day = weeks.get(week, {}).get(dname, [])
    if not lessons_day:
        return (f"{label} ({dname}, {'II' if week == '2' else 'I'} неделя) у группы {group} "
                f"пар нет. 🐯", {"day": dname, "count": 0})
    body = "\n• ".join(fmt(l) for l in lessons_day)
    return (f"{label} ({dname}), {'II' if week == '2' else 'I'} неделя — группа {group}:\n• "
            + body, {"day": dname, "count": len(lessons_day)})


#Сколько домашних заданий показываем в ответе. Больше — это уже не ответ, а простыня:
#человек спрашивает «что задали», имея в виду ближайшее, а не всю историю за семестр.
_HOMEWORK_LIMIT = 5


def _homework_answer(lessons, records: dict, subject: str = "") -> dict:
    """Ответ про домашние задания. Общий для студента, преподавателя и родителя.

    ДЗ — обычный тип занятия (`Lesson.type == "ДЗ"`, §14), текст задания лежит в поле
    «тема». Раньше на этот вопрос отвечать было нечем: своего интента не существовало, и
    «что задали по физике» уходило в оценки — то есть Вектор уверенно отвечал НЕ НА ТОТ
    вопрос. Здесь же показываем и статус («сдано»/«не сдано»), потому что второй вопрос
    после «что задали» всегда «а я сдал?».

    `records` пуст → статус не показываем (преподаватель спрашивает про группу целиком,
    и «сдано» относилось бы непонятно к кому)."""
    hw = [l for l in lessons if (l.type or "").strip().upper() == "ДЗ"]
    if subject:
        hw = [l for l in hw if l.subject == subject]
    if not hw:
        where = f" по предмету «{subject}»" if subject else ""
        return {"text": f"Домашних заданий{where} пока нет. 🐯", "mood": "happy",
                "intent": "homework", "facts": {"count": 0}}

    #Свежие сверху: спрашивают про то, что задали недавно. Дата в формате ДД.ММ.ГГГГ,
    #поэтому сортируем по перевёрнутому виду, а не по строке как есть.
    def _key(lesson):
        parts = (lesson.date or "").split(".")
        return "".join(reversed(parts)) if len(parts) == 3 else ""

    hw.sort(key=_key, reverse=True)
    shown, lines = hw[:_HOMEWORK_LIMIT], []
    #Задания из НЕСКОЛЬКИХ групп подписываем группой: у преподавателя «Базы данных №1»
    #трёх групп выглядели тремя одинаковыми строками — как дубль (находка 28.09.2026).
    many_groups = len({l.group_name for l in hw}) > 1
    for lesson in shown:
        task = (lesson.topic or "").strip() or "без описания"
        head = f"{lesson.subject} №{lesson.number}" if lesson.number else lesson.subject
        if many_groups:
            head += f" ({lesson.group_name})"
        when = f" от {lesson.date}" if lesson.date else ""
        mark = records.get(lesson.id) if records else None
        status = ""
        if records:
            #«Н» на домашней работе значит «не сдал», а не «не был» (§14) — так и пишем.
            status = " — не сдано" if mark == "Н" else (f" — оценка {mark}" if mark else " — ждёт сдачи")
        lines.append(f"{head}{when}: {task}{status}")
    tail = f" Показал последние {len(shown)} из {len(hw)}." if len(hw) > len(shown) else ""
    return {"text": "Домашние задания:\n• " + "\n• ".join(lines) + "." + tail,
            "mood": "neutral", "intent": "homework",
            #no_voice: список заданий содержит формулировки преподавателя, и LLM их
            #перепишет — а это ровно то, что человек должен прочитать дословно.
            "no_voice": True, "facts": {"count": len(hw)}}


def _human_bytes(n) -> str:
    """Байты человеку: «1.3 ГБ». Вектор говорит словами, а не числами со степенями."""
    if not n:
        return "—"
    units, value, i = ("Б", "КБ", "МБ", "ГБ", "ТБ"), float(n), 0
    while value >= 1024 and i < len(units) - 1:
        value, i = value / 1024, i + 1
    return f"{round(value)} {units[i]}" if value >= 10 or i == 0 else f"{value:.1f} {units[i]}"


#Хук «спросить о состоянии сервера сам бой» (02.10.2026). Ставит его программа
#(`desktop/local_api.install_remote_vector`), на бою он пуст — и поведение там прежнее.
#fn() -> dict ответа боевого `/web/vector/ask` | None (нет связи, истёк вход).
_remote_server_state = None


def set_remote_server_state(fn) -> None:
    global _remote_server_state
    _remote_server_state = fn


def _server_state_from_prod() -> dict:
    """Ответ о состоянии сервера в ПРОГРАММЕ — с боя, тем же расчётом, что на сайте.

    Источник один: бой считает свои диск, память, базу и копии сам (ниже, `hostinfo`), а
    программа лишь передаёт его ответ. Пересчитывать здесь было бы нечем — `hostinfo` в
    программе мерит компьютер человека."""
    remote = None
    if _remote_server_state is not None:
        try:
            remote = _remote_server_state()
        except Exception as e:      # noqa: BLE001 — сбой связи не роняет ответ Вектора
            print(f"[vector] состояние сервера с боя не получено: {e}")
    if isinstance(remote, dict) and remote.get("intent") == "server_state" and remote.get("text"):
        return {"text": str(remote["text"]), "mood": remote.get("mood") or "neutral",
                "intent": "server_state", "no_voice": True,
                "facts": dict(remote.get("facts") or {}, source="server")}
    return {"text": ("Не получилось спросить сервер: нет связи или истёк вход. Про этот "
                     "компьютер отвечать не буду — вопрос был о сервере. Когда связь "
                     "появится, спросите ещё раз или откройте раздел «Сервер»."),
            "mood": "neutral", "intent": "server_state", "no_voice": True,
            "facts": {"source": "unavailable"}}


def _server_state_facts(db: Session) -> dict:
    """Состояние машины для администратора: диск, память, база, резервные копии.

    Цифры берутся у самой машины (`hostinfo`) — тем же способом, что их показывает
    раздел «Сервер». Второго источника не заводим: разойдутся, и человек получит два
    разных ответа на один вопрос в зависимости от того, где спросил.

    ⚠️ ОТВЕТ НЕ ОЗВУЧИВАЕТСЯ (`no_voice`). Здесь одни числа, а LLM их «оживляет» —
    округляет, меняет единицы, добавляет несуществующее. Для успеваемости это правило
    у нас давно, и к состоянию сервера оно относится ровно так же.

    🔥 В ПРОГРАММЕ ЭТОТ ОТВЕТ БЫЛ ПРАВДОПОДОБНОЙ ЛОЖЬЮ (живой прогон 01.10.2026). Вектор
    там отвечает с ЛОКАЛЬНОГО сервера, то есть `hostinfo` мерил компьютер администратора:
    «база зашифрована» (это его локальная копия), «резервных копий НЕ НАЙДЕНО» (их нет на
    ноутбуке), — тогда как раздел «Сервер» пересылается на бой и показывал настоящую
    машину. Два разных ответа на один вопрос — ровно то, от чего предостерегает абзац
    выше. В копии ответ берётся С БОЯ (`_server_state_from_prod`), как и у раздела.
    ⚠️ Признак «копия» — тот же `GRADEBOOK_LOCAL_COPY`, что глушит пуши (`config.push_enabled`)."""
    if os.environ.get("GRADEBOOK_LOCAL_COPY", "") == "1":
        return _server_state_from_prod()
    from ... import hostinfo
    from ...routers.serverinfo import _db_file, _deploy_root

    info = hostinfo.summary(_deploy_root())
    disk, mem = info.get("disk") or {}, info.get("memory") or {}
    parts = []
    if disk.get("total"):
        used = round(disk["used"] / disk["total"] * 100)
        parts.append(f"диск занят на {used}% ({_human_bytes(disk['free'])} свободно)")
    if mem.get("total"):
        used = round(mem["used"] / mem["total"] * 100)
        parts.append(f"память — {used}% из {_human_bytes(mem['total'])}")
    days = int((info.get("uptime") or 0) // 86400)
    hours = int(((info.get("uptime") or 0) % 86400) // 3600)
    if days or hours:
        parts.append(f"работает {days} д {hours} ч")

    path, size, encrypted = _db_file(), 0, False
    try:
        from ...db import DB_KEY
        encrypted = bool(DB_KEY)
        if path and os.path.isfile(path):
            size = os.path.getsize(path)
    except Exception:      # noqa: BLE001 — сведения о базе не повод ронять ответ
        pass
    if size:
        parts.append(f"база — {_human_bytes(size)}"
                     + (", зашифрована" if encrypted else ", БЕЗ шифрования"))

    #Свежесть копий — первое, что админ хочет знать про сервер, и первое, о чём забывают.
    backup_dir = os.environ.get("GRADEBOOK_BACKUP_DIR") or "/root/gb-backups"
    latest = ""
    if os.path.isdir(backup_dir):
        items = hostinfo.listdir(backup_dir, backup_dir)
        if items:
            latest = max(i["mtime"] for i in items)
    parts.append(f"последняя резервная копия — {latest}" if latest
                 else "резервных копий НЕ НАЙДЕНО")

    #Тревожное состояние Вектор обязан назвать тревогой, а не спрятать в перечисление.
    alarm = (not latest) or (disk.get("total") and disk["used"] / disk["total"] > 0.9)
    return {"text": "Сервер: " + "; ".join(parts) + ".",
            "mood": "sad" if alarm else "neutral", "intent": "server_state",
            "no_voice": True,
            "facts": {"disk": disk, "memory": mem, "db_size": size,
                      "db_encrypted": encrypted, "latest_backup": latest}}


def _group_names(db: Session) -> list:
    """Все группы справочника — чтобы узнать группу, названную в вопросе («студенты К74/1»)."""
    try:
        rows = db.query(Group.name).filter(Group.deleted == False).all()  # noqa: E712
        return sorted({r[0] for r in rows if r[0]})
    except Exception:      # noqa: BLE001 — без списка групп Вектор всё равно отвечает
        return []


def _groups_with_students(db: Session) -> list:
    """Группы, где есть хотя бы один студент. В справочнике на бою ~300 групп — весь
    каталог портала, — а журнал ведётся у единиц: сводка по пустым была бы шумом."""
    rows = (db.query(User.group_name)
            .filter(User.role == "student", User.deleted == False)  # noqa: E712
            .distinct().all())
    return sorted({r[0] for r in rows if r[0]})


def _plan_lessons(db: Session, cfg: dict, group: str) -> list:
    """Занятия группы для сводок: текущий термин и только предметы действующего плана —
    тот же отбор, что у кабинета студента, иначе Вектор и экран студента разойдутся."""
    return W.current_term_lessons(db, group, W.current_subject_lessons(
        db, group, W.group_lessons(db, group)), cfg)


def _student_rows(db: Session, cfg: dict, group: str, lessons: list, scale=None) -> list:
    """По студенту группы: средний, долги, пропуски и риск отчисления — ОДИН сбор на все
    сводки Вектора (должники, зона риска, пропуски, «сводка по группе»).

    Риск — тот же индекс `dropout_risk`, что на дашбордах, и тот же порог
    (`W.counts_as_at_risk`): иначе Вектор и экран называли бы разное число людей."""
    out = []
    for s in W.students_in_group(db, group):
        own = W.filter_lessons_by_student_subgroup(db, lessons, s.id)
        rec = W.student_records(db, s.surname, s.name, group, student_id=s.id)
        sc = scale if scale is not None else W.lesson_scale_map(db, own)
        out.append({"student": s, "group": group, "lessons": own, "records": rec,
                    "scale": sc, "average": W.average(own, rec, cfg, scale=sc),
                    "debts": _debts_by_subject(own, rec, sc),
                    "absences": W.absences(own, rec),
                    "risk": W.dropout_risk_for_student(db, s.surname, s.name, group, cfg=cfg,
                                                       lessons=own, records=rec,
                                                       student_id=s.id)})
    return out


def _debts_by_subject(lessons: list, records: dict, scale) -> list:
    """Долги С НАЗВАНИЕМ ПРЕДМЕТА: «Математика: практика №2 не сдана (2), …».

    🔥 Без предмета список долгов выглядел сломанным (находка живого прогона 28.09.2026):
    у студента с пятью предметами «практика №2 не сдана» повторялась пять раз подряд, и
    это читалось как глюк, а не как пять разных долгов."""
    out = []
    for subject in sorted({l.subject for l in lessons if l.subject}):
        d = W.debts([l for l in lessons if l.subject == subject], records, scale=scale)
        if d:
            out.append(f"{subject}: " + ", ".join(d))
    return out


def _group_avg(rows: list) -> float:
    vals = [r["average"] for r in rows if r["average"] > 0]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def _summary_line(group: str, rows: list) -> str:
    """Одна строка сводки по группе: сколько студентов, средний, должники, риск, пропуски."""
    avg = _group_avg(rows)
    debtors = sum(1 for r in rows if r["debts"])
    risky = sum(1 for r in rows if W.counts_as_at_risk(r["risk"]))
    missed = sum(r["absences"]["всего"] for r in rows)
    avg_txt = f"средний {avg}" if avg else "оценок пока нет"
    return (f"{group}: студентов {len(rows)}, {avg_txt}, должников {debtors}, "
            f"в зоне риска {risky}, пропущено {missed} ч")


def _who(row: dict) -> str:
    return f"{W.display_name(row['student'])} ({row['group']})"


def _debtors_answer(rows: list, scope: str) -> dict:
    """«Должники» — только те, у кого ЕСТЬ долг, с предметами. Зона риска — отдельный
    вопрос и отдельный ответ (раньше у преподавателя они были склеены в один список под
    заголовком «задолженности», куда попадали и люди без единого долга)."""
    found = [r for r in rows if r["debts"]]
    if not found:
        return {"text": f"Должников {scope} нет. 🐯", "mood": "happy", "intent": "debtors",
                "facts": {"count": 0}, "no_voice": True}
    lines = [f"• {_who(r)}: " + "; ".join(r["debts"]) for r in found[:25]]
    tail = f"\n…и ещё {len(found) - 25}." if len(found) > 25 else ""
    return {"text": f"Должники {scope} — {len(found)}:\n" + "\n".join(lines) + tail,
            "mood": "sad", "intent": "debtors", "facts": {"count": len(found)},
            "no_voice": True}


def _risk_answer(rows: list, scope: str) -> dict:
    found = [r for r in rows if W.counts_as_at_risk(r["risk"])]
    if not found:
        return {"text": f"В зоне риска {scope} никого нет. 🐯", "mood": "happy",
                "intent": "at_risk", "facts": {"at_risk": 0}, "no_voice": True}
    found.sort(key=lambda r: -int(r["risk"].get("score") or 0))
    lines = [f"• {_who(r)}: " + (W.dropout_risk.summary_line(r["risk"]) or "риск отчисления")
             + (f", средний {r['average']}" if r["average"] else "") for r in found[:25]]
    tail = f"\n…и ещё {len(found) - 25}." if len(found) > 25 else ""
    return {"text": f"В зоне риска {scope} — {len(found)} (индекс риска отчисления, тот же, "
                    f"что на дашбордах):\n" + "\n".join(lines) + tail,
            "mood": "sad", "intent": "at_risk", "facts": {"at_risk": len(found)},
            "no_voice": True}


def _absences_answer(rows: list, scope: str) -> dict:
    found = sorted((r for r in rows if r["absences"]["всего"]),
                   key=lambda r: -r["absences"]["всего"])
    total = sum(r["absences"]["всего"] for r in rows)
    if not found:
        return {"text": f"Пропусков {scope} нет. 🐯", "mood": "happy", "intent": "absences",
                "facts": {"hours": 0}, "no_voice": True}
    lines = [f"• {_who(r)}: {r['absences']['всего']} ч (Н: {r['absences']['Н']}, "
             f"Б: {r['absences']['Б']})" for r in found[:10]]
    tail = f"\n…и ещё {len(found) - 10}." if len(found) > 10 else ""
    return {"text": f"Пропущено {scope}: {total} ч. Больше всего:\n" + "\n".join(lines) + tail,
            "mood": "neutral", "intent": "absences", "facts": {"hours": total},
            "no_voice": True}


def _roster_answer(db: Session, groups: list) -> dict:
    parts, total = [], 0
    for g in groups:
        names = [W.display_name(s) for s in W.students_in_group(db, g)]
        total += len(names)
        parts.append(f"{g} ({len(names)}): " + (", ".join(names) if names else "список пуст"))
    return {"text": "Студенты группы " + "\n".join(parts) if len(groups) == 1
            else "Студенты ваших групп:\n" + "\n".join(parts),
            "mood": "neutral", "intent": "roster",
            "facts": {"groups": len(groups), "count": total}, "no_voice": True}


def _find_students(db: Session, surnames, groups=None) -> list:
    """Студенты с любой из фамилий-кандидатов (`vector_nlu.find_surnames`).

    Кандидатов бывает несколько, и это не ошибка разбора: «Алексеева» — и родительный
    падеж от Алексеев, и женская фамилия Алексеева. До 01.10.2026 искали ОДНУ фамилию
    точным равенством, и женщина Алексеева не находилась вовсе, если в колледже был
    мужчина Алексеев (живой прогон: админ видел двух Алексеевых из десяти)."""
    if isinstance(surnames, str):
        surnames = [surnames]
    names = [x for x in (surnames or []) if x]
    if not names:
        return []
    rows = (db.query(User).filter(User.role == "student", User.deleted == False,  # noqa: E712
                                  User.surname.in_(names)).all())
    if groups is not None:
        rows = [s for s in rows if s.group_name in groups]
    return sorted(rows, key=lambda s: (s.group_name or "", W.display_name(s)))


def _name_token_matches(token: str, name: str) -> bool:
    """Слово вопроса — это имя или отчество в каком-то падеже? «евгения» ↔ Евгений,
    «кириллу» ↔ Кирилл, «эрдэмовича» ↔ Эрдэмович. Основа — имя без последней гласной
    (у коротких — целиком), хвост не длиннее трёх букв: иначе «Бато» ловился бы внутри
    отчества «Батоевич»."""
    n = vector_nlu.normalize(name)
    if not n or len(token) < 3:
        return False
    stem = n[:-1] if len(n) > 4 and n[-1] in "аяйьоеиуы" else n
    return token.startswith(stem) and len(token) <= len(n) + 3


def _narrow_by_name(rows: list, msg: str, surnames) -> list:
    """Из однофамильцев оставить тех, чьё ИМЯ (и отчество) названо в вопросе.

    🔥 Без этого «Борисов Кирилл» при двух Борисовых в ОДНОЙ группе было тупиком: Вектор
    просил «уточните группу», а группа у обоих одна (живой прогон 01.10.2026). Слова,
    которые и так совпали с фамилией, в счёт не идут — «Егорова» не должна сойти за имя
    «Егор». Имя весит больше отчества; никто не подошёл — список прежний, не угадываем."""
    if len(rows) <= 1:
        return rows
    surname_words = set()
    for sn in surnames or []:
        surname_words |= vector_nlu.surname_forms(sn)
    toks = [t for t in vector_nlu.tokens(msg) if len(t) >= 3 and t not in surname_words]
    if not toks:
        return rows

    def score(s) -> int:
        parts = (s.name or "").split()
        first = parts[0] if parts else ""
        patr = s.patronymic or (parts[1] if len(parts) > 1 else "")
        sc = 2 if first and any(_name_token_matches(t, first) for t in toks) else 0
        if patr and any(_name_token_matches(t, patr) for t in toks):
            sc += 1
        return sc

    scored = [(score(s), s) for s in rows]
    best = max(sc for sc, _s in scored)
    return rows if best == 0 else [s for sc, s in scored if sc == best]


_NAMESAKES_SHOWN = 12


def _namesakes_answer(surname: str, rows: list) -> dict:
    """Тёзки — переспросить, а не выбрать первого: «оценка не тому студенту» хуже ответа
    с уточнением (правило J08 синка, здесь то же). Подсказываем ОБА способа уточнить —
    группу и имя: при двух тёзках в одной группе одна группа не помогает."""
    shown = rows[:_NAMESAKES_SHOWN]
    listed = "; ".join(f"{W.display_name(s)} ({s.group_name or 'без группы'})" for s in shown)
    more = len(rows) - len(shown)
    tail = f" …и ещё {more}" if more > 0 else ""
    first = (rows[0].name or "").split()
    example_name = f"{rows[0].surname} {first[0]}" if first else rows[0].surname
    return {"text": f"Подходят несколько студентов ({len(rows)}): {listed}{tail}. Уточните "
                    f"имя или группу — например «{example_name}» или "
                    f"«{rows[0].surname} {rows[0].group_name}».",
            "mood": "neutral", "intent": "help", "facts": {"count": len(rows)},
            "no_voice": True}


#Намерения, в которых фамилия означает «покажи данные ЭТОГО студента».
_STUDENT_DATA_INTENTS = {"grades", "average", "absences", "debtors", "grade_count",
                         "subject_grades", "zet", "at_risk", "homework", "unknown",
                         "group_stats", "roster"}


def _college_student_surnames(db: Session) -> list:
    rows = (db.query(User.surname).filter(User.role == "student",
                                          User.deleted == False).distinct().all())  # noqa: E712
    return sorted({r[0] for r in rows if r[0] and len(r[0].strip()) >= 2})


def _outside_scope_answer(msg: str, nlu: dict, user: User, db: Session,
                          parent_view: bool) -> dict | None:
    """Вопрос о студенте, которого спрашивающему видеть НЕЛЬЗЯ, — честный отказ.

    🔥 Раньше такой вопрос не опознавался вовсе: фамилии ищутся только среди «своих», и
    «пропуски у Егорова» у студента возвращало ЕГО СОБСТВЕННЫЕ пропуски так, будто это
    ответ про Егорова; у преподавателя чужая фамилия давала сводку по его группам или
    «с радостью бы поболтал» (живой прогон 01.10.2026). Человек не мог понять, что
    случилось: Вектор не понял, сломался или прячет. Отказ называет причину и кто видит.
    Схема доступа — docs/security/VECTOR-ACCESS.md."""
    role = user.role
    if role == "admin" or nlu["intent"] not in _STUDENT_DATA_INTENTS:
        return None
    if role == "moderator":
        #Модератор — сотрудник БЕЗ доступа к успеваемости: любая фамилия студента в
        #вопросе — отказ, а не справка «я умею…», из которой не понять, почему молчу.
        named = nlu.get("surnames") or vector_nlu.find_surnames(
            msg, _college_student_surnames(db))
        if not named:
            return None
        return {"text": "Успеваемость студентов модератору не показываю — это данные "
                        "преподавателей, куратора и администрации.",
                "mood": "neutral", "intent": "help", "facts": {}, "no_voice": True}
    if nlu.get("surnames"):
        return None
    outside = vector_nlu.find_surnames(msg, _college_student_surnames(db))
    if role == "student":
        own = vector_nlu.surname_forms(user.surname or "")
        outside = [x for x in outside if vector_nlu.normalize(x) not in own]
    if not outside:
        return None
    if parent_view:
        text = ("Я рассказываю только об успеваемости вашего ребёнка — данные других "
                "студентов закрыты. 🐯")
    elif role == "student":
        text = ("Я рассказываю только о твоей успеваемости — оценки и пропуски других "
                "студентов закрыты. Спроси, например: «мои оценки», «мои пропуски». 🐯")
    elif role == "teacher":
        text = (f"Студент «{outside[0]}» не в ваших группах — его успеваемость видят его "
                "преподаватели, куратор и администрация.")
    else:
        text = ("Успеваемость студентов модератору не показываю — это данные "
                "преподавателей, куратора и администрации.")
    return {"text": text, "mood": "neutral", "intent": "help", "facts": {},
            "no_voice": True}


def _student_card(db: Session, cfg: dict, stud, intent: str, lessons=None, scale=None,
                  subject: str = "") -> dict:
    """Ответ о КОНКРЕТНОМ студенте для сотрудника (админ, преподаватель): пропуски, долги,
    счёт оценок или полная карточка. Занятия — те, что сотрудник вправе видеть:
    преподаватель передаёт свои, админу — весь действующий план группы."""
    group = stud.group_name or ""
    base = lessons if lessons is not None else _plan_lessons(db, cfg, group)
    own = W.filter_lessons_by_student_subgroup(db, base, stud.id)
    if subject:
        own = [l for l in own if l.subject == subject]
    rec = W.student_records(db, stud.surname, stud.name, group, student_id=stud.id)
    sc = scale if scale is not None else W.lesson_scale_map(db, own)
    who = f"{W.display_name(stud)} ({group})"
    where = f" по предмету «{subject}»" if subject else ""
    facts = {"student": W.display_name(stud), "group": group}
    if subject:
        facts["subject"] = subject
    if intent == "absences":
        a = W.absences(own, rec)
        return {"text": f"{who}{where}: пропусков {a['всего']} ч (Н: {a['Н']}, Б: {a['Б']}, "
                        f"О: {a['О']}).", "mood": "neutral", "intent": "absences",
                "facts": {**facts, **a}, "no_voice": True}
    debts = _debts_by_subject(own, rec, sc)
    if intent == "debtors":
        text = (f"{who}: задолженностей{where} нет." if not debts
                else f"{who}, долги: " + "; ".join(debts) + ".")
        return {"text": text, "mood": "happy" if not debts else "sad", "intent": "debtors",
                "facts": {**facts, "debts": len(debts)}, "no_voice": True}
    if intent == "grade_count":
        b = _grade_breakdown(own, rec, scale=sc)
        return {"text": f"{who}{where}: оценок — {b['всего']} (5: {b['5']}, 4: {b['4']}, "
                        f"3: {b['3']}, 2: {b['2']}).", "mood": "neutral",
                "intent": "grade_count", "facts": {**facts, **b}, "no_voice": True}
    avg = W.average(own, rec, cfg, scale=sc)
    a = W.absences(own, rec)
    parts = [f"{who}{where}: средний балл {avg if avg else '— (оценок пока нет)'}"]
    if not subject:
        per = [p for p in W.per_subject_averages(own, rec, cfg, scale=sc) if p["average"]]
        if per:
            parts.append("по предметам: " + ", ".join(f"{p['subject']} — {p['average']}"
                                                      for p in per))
    parts.append("долги: " + "; ".join(debts) if debts else "долгов нет")
    parts.append(f"пропусков {a['всего']} ч")
    risk = W.dropout_risk_for_student(db, stud.surname, stud.name, group, cfg=cfg,
                                      lessons=own, records=rec, student_id=stud.id)
    if W.counts_as_at_risk(risk):
        line = W.dropout_risk.summary_line(risk)
        parts.append(line[:1].lower() + line[1:])
    return {"text": "; ".join(parts) + ".", "mood": _mood_by_avg(avg),
            "intent": "grades" if intent != "subject_grades" else "subject_grades",
            "facts": {**facts, "average": avg, "debts": len(debts), "absences": a["всего"]},
            "no_voice": True}


def _teachers_answer(db: Session, group: str = "") -> dict:
    """Преподаватели: учётные записи журнала И те, кого называет расписание портала ВСГУТУ.

    🔥 До 28.09.2026 Вектор знал только преподавателей с учётной записью — заведённых
    администратором вручную. Остальные, кто ведёт пары по расписанию портала, для него не
    существовали (жалоба Ярослава). Портал берём из того же снимка и тем же разбором, что
    подсказки назначений в админке (`schedule_web.full_state`, `_portal_subject_teachers`,
    `teacher_match`), — снимок из кэша, в сеть на пути ответа не ходим."""
    from ... import schedule_web
    from .write import _portal_subject_teachers
    import teacher_match

    accounts = db.query(User).filter(User.role == "teacher", User.deleted == False).all()  # noqa: E712
    snap, building = schedule_web.full_state()
    portal = _portal_subject_teachers(snap) if snap is not None and snap.groups else {}
    note = (" Расписание портала ещё загружается — преподавателей оттуда покажу чуть позже."
            if building and not portal else "")
    def clean(raw: str) -> str:
        """«ПО ЮМАТОВА А.С.» → «ЮМАТОВА А.С.»: разбор ячейки портала склеивает хвост
        названия предмета с фамилией. Без инициалов («Преподаватель») — не человек."""
        sur, first, patr = teacher_match.parse_portal_name(raw)
        initials = "".join(f"{x}." for x in (first, patr) if x)
        return f"{sur} {initials}" if sur and initials else ""

    if group:
        by_teacher: dict = {}
        for (g, subject), who in portal.items():
            if g != group:
                continue
            for raw in who:
                name = clean(raw)
                if name:
                    by_teacher.setdefault(name, set()).add(subject)
        if not by_teacher:
            return {"text": f"В расписании портала у группы {group} преподаватели не указаны."
                            + note, "mood": "neutral", "intent": "teachers",
                    "facts": {"count": 0}, "no_voice": True}

        def subjects_of(names):
            #«Технология разработки» и «Технология разработки ПО» — один предмет, у
            #которого портал обрезал хвост в одной из ячеек: оставляем полное название.
            return sorted(s for s in names if not any(o != s and o.startswith(s) for o in names))

        body = "; ".join(f"{t} — {', '.join(subjects_of(s))}" for t, s in sorted(by_teacher.items()))
        return {"text": f"Преподаватели группы {group} по расписанию портала: {body}.",
                "mood": "neutral", "intent": "teachers",
                "facts": {"count": len(by_teacher)}, "no_voice": True}
    names = sorted(W.display_name(t) for t in accounts)
    text = (f"Преподаватели с учётной записью в журнале ({len(names)}): "
            + (", ".join(names) if names else "пока никого") + ".")
    known = [{"id": u.id, "surname": u.surname or "", "name": u.name or "",
              "patronymic": getattr(u, "patronymic", "") or "",
              "full_name": u.full_name or ""} for u in accounts]
    raw = sorted({clean(t) for who in portal.values() for t in who} - {""})
    extra = [t for t in raw if teacher_match.match_teacher(t, known).get("status") != "matched"]
    if extra:
        shown = extra[:40]
        text += (f" По расписанию портала ведут ещё {len(extra)} без учётной записи: "
                 + ", ".join(shown) + (f" и ещё {len(extra) - len(shown)}"
                                       if len(extra) > len(shown) else "") + ".")
    return {"text": text + note, "mood": "neutral", "intent": "teachers",
            "facts": {"count": len(names), "portal_only": len(extra)}, "no_voice": True}


def _pending_registrations(db: Session) -> int:
    try:
        return db.query(RegistrationRequest).filter(
            RegistrationRequest.status == "pending").count()
    except Exception:      # noqa: BLE001 — сводка не повод ронять ответ
        return 0


def _admin_facts(msg: str, nlu: dict, db: Session, cfg: dict) -> dict:
    """Вектор АДМИНИСТРАТОРА: весь колледж, любая группа, любой студент.

    🔥 ПЕРЕПИСАНО 28.09.2026 (жалоба Ярослава). Здесь было шесть веток, а всё остальное —
    «сводка группы», «средний балл», «пропуски», «расписание К74/1», «оценки <фамилия>» —
    проваливалось в один и тот же счётчик «в системе студентов 26…». GigaChat
    переписывал его как «в вашей группе 26 студентов», хотя группы у администратора нет.
    Поэтому все ответы здесь — `no_voice`: модель искажала сам СМЫСЛ административной
    сводки, а не только стиль."""
    intent, group, surname = nlu["intent"], nlu["group"], nlu["surname"]
    subject, day = nlu["subject"], nlu["day"]
    if intent == "server_state":
        return _server_state_facts(db)
    if intent == "schedule":
        if not group:
            return {"text": "Назовите группу — например «расписание К74/1 на завтра».",
                    "mood": "neutral", "intent": "schedule", "facts": {}, "no_voice": True}
        text, facts = _schedule_answer(db, group, msg, day)
        return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
    if intent == "teachers":
        return _teachers_answer(db, group)
    if intent == "subjects":
        if group:
            names = W.group_subject_list(db, group)
            return {"text": f"Предметы группы {group} ({len(names)}): "
                            + (", ".join(names) if names else "не закреплены") + ".",
                    "mood": "neutral", "intent": "subjects",
                    "facts": {"count": len(names)}, "no_voice": True}
        rows = db.query(Subject).filter(Subject.deleted == False).all()  # noqa: E712
        names = sorted({s.name for s in rows if s.name})
        return {"text": f"Предметы колледжа ({len(names)}): "
                        + (", ".join(names) if names else "каталог пуст") + ".",
                "mood": "neutral", "intent": "subjects", "facts": {"count": len(names)},
                "no_voice": True}
    active = _groups_with_students(db)
    if intent == "groups":
        names = _group_names(db)
        n_all = len(names)
        #Небольшой справочник называем целиком; на бою в нём ~300 групп — весь каталог
        #портала, и перечень сотни пустых названий был бы шумом вместо ответа.
        if n_all <= 40:
            body = ", ".join(f"{g} ({len(W.students_in_group(db, g))} студ.)" if g in active
                             else g for g in names)
            text = f"Группы колледжа ({n_all}): {body}." if names else "Групп пока нет."
        else:
            body = ", ".join(f"{g} ({len(W.students_in_group(db, g))})" for g in active)
            text = (f"Групп со студентами — {len(active)}: {body}." if active
                    else "Групп со студентами пока нет.")
            text += (f" Всего в справочнике {n_all}: остальные — группы из расписания "
                     "портала без студентов в журнале.")
        return {"text": text, "mood": "neutral", "intent": "groups",
                "facts": {"groups": len(active), "catalog": n_all}, "no_voice": True}

    # ── вопрос о конкретном студенте ───────────────────────────────────────────────
    if surname:
        candidates = nlu.get("surnames") or [surname]
        found = _narrow_by_name(_find_students(db, candidates, [group] if group else None),
                                msg, candidates)
        if len(found) > 1:
            return _namesakes_answer(surname, found)
        if found:
            if intent == "zet":
                s = found[0]
                return _zet_facts(db, s.surname, s.name, s.group_name or "", cfg,
                                  student_id=s.id,
                                  who=f"{W.display_name(s)} ({s.group_name or ''})")
            return _student_card(db, cfg, found[0], intent, subject=subject)
        return {"text": f"Студента «{surname}»" + (f" в группе {group}" if group else "")
                        + " не нашёл.", "mood": "neutral", "intent": "help", "facts": {},
                "no_voice": True}

    if intent == "roster":
        if group:
            return _roster_answer(db, [group])
        body = "; ".join(f"{g} — {len(W.students_in_group(db, g))}" for g in active)
        total = sum(len(W.students_in_group(db, g)) for g in active)
        return {"text": f"Студентов в колледже — {total}. По группам: {body or 'групп нет'}. "
                        "Список покажу по группе: «студенты К74/1».",
                "mood": "neutral", "intent": "roster", "facts": {"count": total},
                "no_voice": True}
    if intent == "homework":
        if not group:
            return {"text": "Домашние задания покажу по группе: «что задали К74/1».",
                    "mood": "neutral", "intent": "homework", "facts": {}, "no_voice": True}
        return _homework_answer(_plan_lessons(db, cfg, group), {}, subject)
    if intent in ("zet", "grade_count"):
        return {"text": "Это считается по студенту — спросите с фамилией: «оценки Иванова», "
                        "«ЗЕТ Петровой».", "mood": "neutral", "intent": "help",
                "facts": {}, "no_voice": True}

    targets = [group] if group else active
    scope = f"в группе {group}" if group else "по колледжу"
    if intent == "subject_grades" and subject:
        vals = []
        for g in targets:
            gl = [l for l in _plan_lessons(db, cfg, g) if l.subject == subject]
            if gl:
                vals.append((g, _group_avg(_student_rows(db, cfg, g, gl))))
        if not vals:
            return {"text": f"По предмету «{subject}» занятий {scope} нет.", "mood": "neutral",
                    "intent": "subject_grades", "facts": {}, "no_voice": True}
        return {"text": f"Средний по предмету «{subject}»: "
                        + "; ".join(f"{g} — {a or 'оценок нет'}" for g, a in vals) + ".",
                "mood": "neutral", "intent": "subject_grades",
                "facts": {"subject": subject, "groups": len(vals)}, "no_voice": True}

    rows = []
    for g in targets:
        rows += _student_rows(db, cfg, g, _plan_lessons(db, cfg, g))
    if intent == "debtors":
        return _debtors_answer(rows, scope)
    if intent == "at_risk":
        return _risk_answer(rows, scope)
    if intent == "absences":
        return _absences_answer(rows, scope)
    # average / group_stats / grades и всё остальное — сводка по группам.
    lines = [_summary_line(g, [r for r in rows if r["group"] == g]) for g in targets]
    n_teachers = db.query(User).filter(User.role == "teacher",
                                       User.deleted == False).count()  # noqa: E712
    n_parents = db.query(User).filter(User.role == "parent",
                                      User.deleted == False).count()  # noqa: E712
    if group:
        text = "Сводка — " + lines[0] + "."
    else:
        text = (f"Сводка по колледжу: студентов {len(rows)} в {len(targets)} группах, "
                f"преподавателей с учётной записью {n_teachers}, родителей {n_parents}."
                + ("\n• " + "\n• ".join(lines) if lines else ""))
    pending = _pending_registrations(db)
    if pending and not group:
        text += f"\n⚠️ Ждут одобрения заявки на регистрацию: {pending}."
    elif "заявк" in msg:
        text += "\nЗаявок на регистрацию, ждущих одобрения, нет."
    return {"text": text, "mood": "neutral" if not pending else "surprised",
            "intent": "group_stats",
            "facts": {"students": len(rows), "groups": len(targets), "teachers": n_teachers,
                      "parents": n_parents, "pending_registrations": pending,
                      "subjects": db.query(Subject).filter(
                          Subject.deleted == False).count()},  # noqa: E712
            "no_voice": True}


def _teacher_facts(msg: str, nlu: dict, user: User, db: Session, cfg: dict,
                   help_text: str) -> dict:
    """Вектор ПРЕПОДАВАТЕЛЯ: только свои группы — по назначениям и по кураторству.

    Курируемая группа видна ЦЕЛИКОМ (все предметы), как на странице «Курирование»; в
    группе, где преподаватель только ведёт, — лишь его предметы. До 28.09.2026 куратор
    без учебной нагрузки получал «за вами нет групп», хотя видел группу на экране."""
    intent, group, surname = nlu["intent"], nlu["group"], nlu["surname"]
    subject, day = nlu["subject"], nlu["day"]
    ty0, ts0 = W.current_term(cfg)
    pairs = W.teacher_assignments(db, user.id, ty0, ts0)
    subjects_by_group: dict = {}
    for g, s in pairs:
        subjects_by_group.setdefault(g, set()).add(s)
    curated = set(user.curated_groups or [])
    groups = sorted(set(subjects_by_group) | curated)
    if not groups:
        return {"text": "За вами пока нет групп — ни нагрузки, ни кураторства. " + help_text,
                "mood": "neutral", "intent": "help", "facts": {}}
    tscale = W.teacher_scale(user)

    def lessons_for(g):
        if g in curated:
            return _plan_lessons(db, cfg, g)
        allowed = subjects_by_group.get(g, set())
        return W.current_term_lessons(
            db, g, [l for l in W.group_lessons(db, g) if l.subject in allowed], cfg)

    def scale_for(g):
        return None if g in curated else tscale

    if intent == "schedule":
        #Расписание публично (страница «Расписание без входа»), поэтому любая группа.
        text, facts = _schedule_answer(db, group or groups[0], msg, day)
        return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
    if intent == "teachers":
        return _teachers_answer(db, group)
    if intent == "groups":
        own = sorted(subjects_by_group)
        parts = []
        if own:
            parts.append("ведёте: " + ", ".join(own))
        if curated:
            parts.append("курируете: " + ", ".join(sorted(curated)))
        return {"text": "Ваши группы — " + "; ".join(parts) + ".", "mood": "neutral",
                "intent": "groups", "facts": {"groups": len(groups)}, "no_voice": True}
    if group and group not in groups:
        return {"text": f"Группа {group} — не ваша: вы работаете с {', '.join(groups)}. Её "
                        "данные видят её преподаватели, куратор и администрация.",
                "mood": "neutral", "intent": "help", "facts": {}, "no_voice": True}
    targets = [group] if group else groups
    scope = f"в группе {group}" if group else "в ваших группах"
    if intent == "subjects":
        own = sorted({s for _g, s in pairs})
        body = "; ".join(f"{g} — " + ", ".join(sorted(subjects_by_group.get(g, ())))
                         for g in sorted(subjects_by_group))
        text = (f"Ваши предметы ({len(own)}): " + ", ".join(own) + f". По группам: {body}."
                if own else "Предметов в вашей нагрузке нет.")
        if curated:
            text += " Курируете: " + ", ".join(sorted(curated)) + "."
        return {"text": text, "mood": "neutral", "intent": "subjects",
                "facts": {"subjects": len(own), "groups": len(groups)}, "no_voice": True}
    if intent == "roster":
        return _roster_answer(db, targets)
    if intent == "homework":
        own = []
        for g in targets:
            own += lessons_for(g)
        return _homework_answer(own, {}, subject)

    # ── вопрос о конкретном студенте ───────────────────────────────────────────────
    if surname and intent in ("absences", "debtors", "grade_count", "grades", "average",
                              "subject_grades", "at_risk", "zet"):
        candidates = nlu.get("surnames") or [surname]
        found = _narrow_by_name(_find_students(db, candidates, targets), msg, candidates)
        if len(found) > 1:
            return _namesakes_answer(surname, found)
        if not found:
            return {"text": f"Студента «{surname}» {scope} не нашёл.", "mood": "neutral",
                    "intent": "help", "facts": {}, "no_voice": True}
        s = found[0]
        if intent == "zet":
            if s.group_name not in curated:
                return {"text": "Зачётные единицы студента видит его куратор и администрация.",
                        "mood": "neutral", "intent": "help", "facts": {}, "no_voice": True}
            return _zet_facts(db, s.surname, s.name, s.group_name or "", cfg, student_id=s.id,
                              who=f"{W.display_name(s)} ({s.group_name or ''})")
        return _student_card(db, cfg, s, intent, lessons=lessons_for(s.group_name),
                             scale=scale_for(s.group_name), subject=subject)

    if intent == "subject_grades" and subject:
        own_groups = [g for g in targets
                      if g in curated or subject in subjects_by_group.get(g, set())]
        if not own_groups:
            return {"text": f"Предмет «{subject}» не в вашей нагрузке — по чужим "
                            "предметам данных не покажу. 🐯",
                    "mood": "neutral", "intent": "help", "facts": {}}
        vals = []
        for g in own_groups:
            gl = [l for l in lessons_for(g) if l.subject == subject]
            vals.append((g, _group_avg(_student_rows(db, cfg, g, gl, scale_for(g)))))
        body = "; ".join(f"{g}: {a}" for g, a in vals)
        return {"text": f"Средний по предмету «{subject}» — {body}.",
                "mood": "neutral", "intent": "subject_grades",
                "facts": {"subject": subject, "groups": len(vals)}}
    if intent in ("grade_count", "zet"):
        #Отвечаем ПРИЧИНОЙ, а не общей справкой: иначе преподаватель решит, что Вектор
        #не понял вопрос, и будет переспрашивать теми же словами.
        what = ("Счёт оценок" if intent == "grade_count" else "Зачётные единицы")
        return {"text": f"{what} веду по студенту — спросите с фамилией, например "
                        "«сколько оценок у Иванова».",
                "mood": "neutral", "intent": "help", "facts": {}}
    if intent == "server_state":
        return {"text": "Состояние сервера — к администратору, это не учебные данные. "
                        "Я могу показать ваши группы, оценки, долги, пропуски, "
                        "домашние задания и расписание. 🐯",
                "mood": "neutral", "intent": "help", "facts": {}}
    if intent not in ("at_risk", "debtors", "absences", "average", "group_stats", "grades"):
        return {"text": help_text, "mood": "neutral", "intent": "help", "facts": {}}

    rows = []
    for g in targets:
        rows += _student_rows(db, cfg, g, lessons_for(g), scale_for(g))
    if intent == "debtors":
        return _debtors_answer(rows, scope)
    if intent == "at_risk":
        return _risk_answer(rows, scope)
    if intent == "absences":
        return _absences_answer(rows, scope)
    lines = [_summary_line(g, [r for r in rows if r["group"] == g]) for g in targets]
    return {"text": "Сводка по вашим группам:\n• " + "\n• ".join(lines) + ".",
            "mood": "neutral", "intent": "group_stats",
            "facts": {"groups": len(targets), "students": len(rows),
                      "at_risk": sum(1 for r in rows if W.counts_as_at_risk(r["risk"]))}}


def _hello_text(user, role: str, locale: str = "ru") -> str:
    """Приветствие: по роли и по имени. Преподаватель, администратор, модератор и родитель —
    «Здравствуйте, Анна Петровна!», студент — «Привет, Арюна!» (28.09.2026, требование
    Ярослава). Имени нет — приветствие без него, а не «Здравствуйте, !»."""
    pack = _STATIC_TEXT.get(locale) if locale != "ru" else None
    prefix = (pack["hello_prefix"] if pack else _HELLO_PREFIX)[role]
    help_text = (pack["help_by_role"] if pack else _HELP_BY_ROLE)[role]
    name = W.address_name(user) if user is not None else ""
    if locale == "zh":
        return f"{prefix}，{name}！{help_text}" if name else f"{prefix}！{help_text}"
    return f"{prefix}, {name}! {help_text}" if name else f"{prefix}! {help_text}"


def _vector_facts(msg: str, user: User, db: Session, cfg: dict, addressee=None) -> dict:
    """Фактический ответ (text/mood/intent/facts) по роли из РЕАЛЬНЫХ данных.

    Единый разбор запроса — vector_nlu.classify (тот же лексикон, что у десктопа). intent
    ВСЕГДА в ответе: по нему клиент выбирает эмоцию/анимацию маскота. Числа — только из SQL.
    `addressee` — к кому обращаться в приветствии (родитель спрашивает данными ребёнка)."""
    role = user.role if user.role in ("student", "teacher", "admin", "moderator") else "student"
    subjects = _known_subjects(user, db)
    surnames = _known_surnames(user, db)
    nlu = vector_nlu.classify(msg, surnames=surnames, subjects=subjects,
                              groups=_group_names(db))
    intent, subject, day = nlu["intent"], nlu["subject"], nlu["day"]
    help_text = _HELP_BY_ROLE[role]
    #Кабинет родителя спрашивает данными РЕБЁНКА (`user` — ребёнок), а читает родитель.
    parent_view = addressee is not None and getattr(addressee, "id", None) != user.id
    refusal = _outside_scope_answer(msg, nlu, user, db, parent_view)
    if refusal:
        return refusal

    # Общие для всех ролей: приветствие / помощь / благодарность / факты о заведении.
    if intent == "hello":
        return {"text": _hello_text(addressee or user, role), "mood": "happy",
                "intent": "hello", "facts": {}}
    if intent in ("help", "unknown"):
        return {"text": help_text, "mood": "happy" if intent == "help" else "neutral",
                "intent": "help" if intent == "help" else "unknown", "facts": {}}
    if intent == "thanks":
        return {"text": "Всегда рад помочь! 🐯", "mood": "happy", "intent": "thanks", "facts": {}}
    if intent == "weather":
        #Погода — такой же факт, как средний балл: берём у метеослужбы, не сочиняем.
        #Нет связи — честное «не знаю» (weather.answer сам это учитывает).
        import weather as _w
        data = _w.current()
        #ВОПРОС передаём целиком: интент срабатывает на слово «погода», а спросить могли
        #про другой город. Без этого аргумента на «погода в Саратове» Вектор уверенно
        #называл температуру Улан-Удэ — неверный ответ с настоящей цифрой (нашёл Влад).
        return {"text": _w.answer(msg),
                "mood": "happy" if data else "neutral",
                "intent": "weather",
                "facts": {"weather": data or {}}}
    if intent == "about_vsgutu":
        return {"text": _ABOUT_VSGUTU, "mood": "neutral", "intent": "about_vsgutu", "facts": {}}
    if intent == "about_college":
        return {"text": _ABOUT_COLLEGE, "mood": "neutral", "intent": "about_college", "facts": {}}
    if intent == "howto":
        return {"text": _howto_text(cfg, role), "mood": "happy", "intent": "howto", "facts": {}}

    if role in ("admin", "teacher"):
        #⚠️ Фамилия в самом вопросе ловится не здесь, а в `answer_vector_question` — для
        #ВСЕХ ролей одной дверью (см. `_names_a_person`).
        return (_admin_facts(msg, nlu, db, cfg) if role == "admin"
                else _teacher_facts(msg, nlu, user, db, cfg, help_text))
    if role == "moderator":
        #Модератор — сотрудник без доступа к успеваемости: раньше роль молча считалась
        #студенческой, и на «сколько студентов» он получал «эти данные — для
        #преподавателя, могу показать ТВОЙ средний балл» (находка живого прогона).
        if intent == "schedule" and nlu["group"]:
            text, facts = _schedule_answer(db, nlu["group"], msg, day)
            return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
        if intent == "teachers":
            return _teachers_answer(db, nlu["group"])
        return {"text": help_text, "mood": "neutral", "intent": "help", "facts": {}}

    # ── СТУДЕНТ: только свои данные (privacy-by-design) ──────────────────────────────
    group = user.group_name
    #Занятия по предметам, убранным из плана группы, не должны попадать ни в долги,
    #ни в средний, ни в «мои оценки» (current_subject_lessons) — и занятия за ПРОШЛЫЕ
    #курсы по повторяющимся предметам вроде «Физической культуры» тоже не должны
    #(current_term_lessons) — та же тройная фильтрация, что в student_overview, плюс
    #раздельное обучение (§ролей, 3.6.1): чужая подгруппа студенту не видна.
    lessons = W.filter_lessons_by_student_subgroup(db, W.current_term_lessons(
        db, group, W.current_subject_lessons(
            db, group, W.group_lessons(db, group)), cfg), user.id)
    #Вектор отвечает СТУДЕНТУ о нём самом — значит теми же правилами, что и его журнал:
    #иначе один и тот же вопрос давал бы разные ответы на двух экранах.
    records = W.student_visible_records(db, user.surname, user.name, group, student_id=user.id)
    scale_map = W.lesson_scale_map(db, lessons)

    if intent == "schedule":
        #Расписание публично (страница «Расписание без входа») — названную группу можно.
        text, facts = _schedule_answer(db, nlu["group"] or group, msg, day)
        return {"text": text, "mood": "neutral", "intent": "schedule", "facts": facts}
    if intent == "groups":
        return {"text": f"Твоя группа — {group}." if group else "Группа за тобой не закреплена.",
                "mood": "neutral", "intent": "groups", "facts": {"group": group}}
    if intent == "teachers":
        #Кто ведёт пары своей группы — открытые данные расписания портала.
        if not group:
            return {"text": "Группа за тобой не закреплена.", "mood": "neutral",
                    "intent": "help", "facts": {}}
        return _teachers_answer(db, group)
    if intent == "debtors":
        d = _debts_by_subject(lessons, records, scale_map)
        text = "Задолженностей нет — так держать! 🐯" if not d else \
            "Есть задолженности: " + "; ".join(d) + "."
        return {"text": text, "mood": "happy" if not d else "sad",
                "intent": "debtors", "facts": {"debts": len(d)}}
    if intent == "absences":
        a = W.absences(lessons, records)
        return {"text": f"Пропусков всего: {a['всего']} (Н: {a['Н']}, Б: {a['Б']}, О: {a['О']}).",
                "mood": "neutral" if a["всего"] else "happy", "intent": "absences", "facts": a}
    if intent == "homework":
        return _homework_answer(lessons, records, subject)
    if intent == "grade_count":
        b = _grade_breakdown(lessons, records, scale=scale_map)
        if subject:
            subj_lessons = [l for l in lessons if l.subject == subject]
            bs = _grade_breakdown(subj_lessons, records, scale=scale_map)
            return {"text": f"Оценок по предмету «{subject}» — {bs['всего']} "
                            f"(5: {bs['5']}, 4: {bs['4']}, 3: {bs['3']}, 2: {bs['2']}).",
                    "mood": "neutral", "intent": "grade_count", "facts": bs}
        return {"text": f"Всего у тебя оценок — {b['всего']} "
                        f"(пятёрок: {b['5']}, четвёрок: {b['4']}, троек: {b['3']}, двоек: {b['2']}).",
                "mood": "happy" if b["2"] == 0 else "neutral",
                "intent": "grade_count", "facts": b}
    if intent == "subject_grades" and subject:
        per = [p for p in W.per_subject_averages(lessons, records, cfg, scale=scale_map)
               if p["subject"] == subject]
        if not per:
            return {"text": f"По предмету «{subject}» у тебя пока нет занятий с оценками.",
                    "mood": "neutral", "intent": "subject_grades", "facts": {}}
        p = per[0]
        marks = [records.get(l.id) for l in lessons
                 if l.subject == subject and l.type == "Практика"
                 and W.grading.to_five_point(records.get(l.id), scale_map.get(l.id, W.grading.DEFAULT_SCALE)) is not None]
        avg_txt = f"средний {p['average']}" if p["average"] else "оценок ещё нет"
        body = (", ".join(marks)) if marks else "—"
        return {"text": f"По предмету «{subject}»: {avg_txt}. Оценки: {body}.",
                "mood": _mood_by_avg(p["average"]), "intent": "subject_grades",
                "facts": {"subject": subject, "average": p["average"]}}
    if intent == "subjects":
        #Полный список предметов группы — из справочника И занятий (group_subject_list),
        #а не только из занятий: предмет из импортированного учебного плана появляется
        #раньше, чем по нему заводят первое занятие, и до этой ветки Вектор о нём молчал.
        #no_voice — перечень НАЗВАНИЙ: LLM, «озвучивая данные», переставляет и выдумывает
        #предметы, а это ровно то, что продукт обещает не делать.
        names = W.group_subject_list(db, group)
        if not names:
            return {"text": "Предметы за твоей группой пока не закреплены — их заводит "
                            "администратор. 🐯",
                    "mood": "neutral", "intent": "subjects", "facts": {"subjects": 0},
                    "no_voice": True}
        graded = {p["subject"] for p in W.per_subject_averages(lessons, records, cfg,
                                                               scale=scale_map)
                  if p["average"]}
        text = f"Твои предметы ({len(names)}): " + ", ".join(names) + "."
        no_marks = [n for n in names if n not in graded]
        if no_marks:
            text += " Пока без оценок: " + ", ".join(no_marks) + "."
        return {"text": text, "mood": "neutral", "intent": "subjects",
                "facts": {"subjects": len(names), "without_grades": len(no_marks)},
                "no_voice": True}
    if intent == "grades" or intent == "subject_grades":
        per = W.per_subject_averages(lessons, records, cfg, scale=scale_map)
        graded = [p for p in per if p["average"]]
        if not graded:
            return {"text": "Оценок по практикам пока нет — как появятся, покажу. 🐯",
                    "mood": "neutral", "intent": "grades", "facts": {}}
        body = "; ".join(f"{p['subject']} — {p['average']}" for p in graded)
        return {"text": f"Твой средний по предметам: {body}.", "mood": "neutral",
                "intent": "grades", "facts": {"subjects": len(graded)}}
    if intent == "zet":
        return _zet_facts(db, user.surname, user.name, group, cfg, student_id=user.id)
    # average и всё остальное (at_risk/roster/group_stats недоступны студенту)
    avg = W.average(lessons, records, cfg, scale=scale_map)
    if intent == "server_state":
        #Состояние сервера — не учебные данные, и студенту их знать незачем. Молчать
        #нельзя: без явной ветки вопрос про диск проваливался бы в средний балл, то
        #есть Вектор отвечал бы уверенно и не на тот вопрос.
        return {"text": "Про сервер знает администратор — это не учебные данные. "
                        "Я могу показать твой средний балл, оценки, пропуски, долги, "
                        "домашние задания и расписание. 🐯",
                "mood": "neutral", "intent": "help", "facts": {}}
    if intent in ("at_risk", "roster", "group_stats"):
        return {"text": "Эти данные — для преподавателя. Я могу показать твой средний балл, "
                        "оценки, пропуски, долги, домашние задания и расписание. 🐯",
                "mood": "neutral", "intent": "help", "facts": {}}
    return {"text": f"Твой средний балл — {avg}. " + W.grading.methodology_text(cfg),
            "mood": _mood_by_avg(avg), "intent": "average", "facts": {"average": avg}}
