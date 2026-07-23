"""
voice_command.py — ДЕТЕРМИНИРОВАННЫЙ разбор голосовой команды преподавателя.

Почему без LLM. По голосу преподаватель ставит оценки/пропуски — юридически значимое
действие (успеваемость, стипендия, отчисление). Доверять извлечение «кому/что/сколько»
языковой модели нельзя: она может «сгаллюцинировать» 5 вместо 2. Здесь — только чёткая
детерминированная логика на реальных данных:
    речь (текст от Whisper) → нормализация → распознавание действия и оценки по обширным
    словарям синонимов → нечёткое сопоставление фамилии с РЕАЛЬНЫМ ростером группы
    (никаких выдуманных имён) → структура ParsedCommand + человекочитаемое резюме.

ПРИНЦИП «ЛУЧШЕ ПЕРЕСПРОСИТЬ, ЧЕМ ОШИБИТЬСЯ». При ЛЮБОЙ неоднозначности возвращаем
ошибку/кандидатов, а не догадку:
  • названо несколько разных оценок («четыре… нет, пять»)     → переспрос;
  • в одной фразе и оценка, и пропуск                          → переспрос;
  • оценка вне шкалы 2–5                                       → отказ;
  • два студента с одной фамилией без имени                    → выбор из кандидатов;
  • похоже, названо несколько разных студентов                → переспрос;
  • фамилия не распознана в этой группе                        → отказ.
Итог ВСЕГДА подтверждается преподавателем в диалоге перед записью (см. UI).

Модуль ЧИСТЫЙ: не ходит в БД. Ростер и сегодняшние занятия передаёт вызывающий код —
так логику легко покрыть тестами и переиспользовать на сервере (веб) в будущем.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

#Словесные оценки → цифра. Много форм (Whisper пишет и «пять», и «пятёрку», и падежи).
_WORD_GRADE = {
    "2": {"два", "две", "двойку", "двойка", "двойки", "двоечку", "двоек", "двояк",
          "двойкой", "двоечка", "неуд", "неудовлетворительно",
          "неудовлетворительная", "неудовлетворительный", "неуды", "неудовл"},
    "3": {"три", "тройку", "тройка", "тройки", "троечку", "троек", "трояк", "тройкой",
          "троечка", "трешку", "трёшку", "трешка", "трёшка", "удовлетворительно",
          "удов", "удовлетворительная", "удовлетворительный", "удовлетвор", "удовлет",
          "удовлетворительно"},
    "4": {"четыре", "четверку", "четверка", "четверки", "четвёрочку", "четверочку",
          "четвёрку", "четверок", "четвёркой", "четверкой", "четвёрочка", "четвёра",
          "четвера", "четвёру", "четверу", "хорошо", "хор", "хорошая", "хороший", "хорошист", "хорошистка"},
    "5": {"пять", "пятерку", "пятерка", "пятерки", "пятёрочку", "пятерочку", "пятёрку",
          "пятерок", "пятёркой", "пятеркой", "пятёрочка", "пятёра", "пятера",
          "пятёру", "пятеру", "отлично", "отл", "отличная", "отличный", "превосходно",
          "отличник", "отличница", "супер"},
}
#Обратный индекс слово→цифра.
_GRADE_BY_WORD = {w: d for d, ws in _WORD_GRADE.items() for w in ws}

#Ключевые ОСНОВЫ для посещаемости (ищем вхождением — ловит склонения/спряжения).
_ABSENCE_O = ("уважительн", "по уважит", "освобожд", "отпросил", "с разрешения",
              "по справке", "справка", "по семейным", "по семейн", "на соревнован",
              "на олимпиад", "по разрешению", "уважит причин", "на конференц",
              "на сборах", "по делам универ", "по учеб причин",
              "с уважительной", "оправдан")
_ABSENCE_B = ("болеет", "болел", "больнич", "по болезни", "болезн", "заболел",
              "температур", "на больнич", "приболел", "простыл", "простуд", "недомога",
              "приболела", "заболела", "плохо себя", "на лечени", "в больниц",
              "по состоянию здоров")
_ABSENCE_N = ("пропуск", "прогул", "отсутств", "не был", "не была", "не были",
              "не пришел", "не пришла", "не явил", "неявк", "прогулял", "прогулива",
              "проспал", "не появил", "отсутствовал", "нет на паре", "нет на занят",
              "нет на лекц", "не присутств", "отсутствует", "нету", "не посетил",
              "пропустил", "пропустила", "прогуливает", "нет в аудитор", "не дошел",
              "не дошла", "не появлял")
#Присутствие (лекция ✓). ВНИМАНИЕ: проверяется ПОСЛЕ негативов, иначе «не пришёл»
#ложно распознается как «пришёл».
_PRESENT = ("присутств", "был на", "была на", "были на", "на месте", "на паре",
            "на лекции", "на занятии", "пришел", "пришла", "явил", "отметь присут",
            "отметь как присут", "посетил", "посетила", "в аудитор", "работал на",
            "работала на", "отметь что был", "отметь что была", "присутствовал",
            "присутствовала", "дошел до", "дошла до")

_ACTION_RU = {
    "grade": "оценку", "present": "присутствие (✓)",
    "absent_n": "пропуск (Н)", "absent_b": "пропуск по болезни (Б)",
    "absent_o": "пропуск по уважительной (О)",
}


#Маркеры ВОПРОСА (информационный запрос, НЕ запись). Если встречаются — команду записи
#НЕ выполняем ни при каких обстоятельствах, а отправляем текст в обычный Q&A Вектора
#(«назови студентов», «какой средний балл», «сколько пропусков у …»). Это защищает от
#случайной записи, когда вопрос содержит слова «оценка»/«пропуск».
_QUESTION_MARKERS = (
    "сколько", "какой", "какая", "какое", "какие", "каков", "назови", "перечисли",
    "перечислите", "покажи", "показать", "список", "кто ", "у кого", "есть ли",
    "средний балл", "средн", "статистик", "успеваемост", "почему", "что ", "чему",
    "когда", "где ", "нужно ли", "можно ли", "?",
)

#Действия, которые ПИШУТ данные (требуют подтверждения преподавателя).
WRITE_ACTIONS = ("grade", "present", "absent_n", "absent_b", "absent_o")


@dataclass
class ParsedCommand:
    ok: bool = False
    is_question: bool = False  #True — это вопрос, не команда записи → в Q&A Вектора
    action: str = ""          #grade | present | absent_n | absent_b | absent_o
    value: str = ""           #«5» | «✓» | «Н» | «Б» | «О»
    student: Optional[Tuple[str, str]] = None   #(фамилия, имя)
    candidates: List[Tuple[str, str]] = field(default_factory=list)
    lesson_id: str = ""
    lesson_label: str = ""
    confidence: float = 0.0   #0..1, нечёткое совпадение фамилии
    summary: str = ""
    error: str = ""
    heard: str = ""           #что распознала модель (для показа преподавателю)


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9/ ]+", " ", s)


#Падежные окончания рус. фамилий/имён (косвенные падежи → к именительному, грубо).
_ENDINGS = ("овым", "евым", "ому", "его", "ого", "ыми", "ева", "ову", "еву", "ове",
            "еве", "ым", "им", "ой", "ей", "ую", "ю", "у", "а", "е", "ы", "и", "я")


def _stem(word: str) -> str:
    s = _norm(word).strip()
    for end in _ENDINGS:
        if len(s) > len(end) + 2 and s.endswith(end):
            return s[: -len(end)]
    return s


#Фонетическая нормализация для УСТОЙЧИВОСТИ к вариантам транскрипции — особенно
#бурятских ФИО, которые Whisper слышит по-разному: «Гындынова/Гундынова/Гэндэнова»,
#«Самбуев/Самбоев», «Баянжаргал» с удвоениями. Схлопываем ТОЛЬКО безопасные пары, которые
#не сливают РАЗНЫЕ русские фамилии: э=е, й=и, мягкий/твёрдый знак убираем, удвоенные
#буквы схлопываем. Рискованные (ы→и, х→г, о→у) НЕ трогаем — иначе «Сидоров» начнёт
#совпадать с «Петров», а парсер обязан не угадывать (test_unknown_surname_no_guess).
_PHON_MAP = str.maketrans({"э": "е", "й": "и", "ъ": "", "ь": ""})


def _phon(word: str) -> str:
    s = _norm(word).translate(_PHON_MAP)
    return re.sub(r"(.)\1+", r"\1", s)   #удвоенные буквы → одна (Баянжаргалл→баянжаргал)


def _similar(a: str, b: str) -> float:
    """Похожесть с фонетической страховкой: берём ЛУЧШЕЕ из прямого сравнения и сравнения
    фонетических форм. Фонетика только ПОВЫШАЕТ совпадение настоящих вариантов имени и не
    может слить разные фамилии (схлопываются лишь безопасные пары)."""
    direct = SequenceMatcher(None, a, b).ratio()
    pa, pb = _phon(a), _phon(b)
    if pa == a and pb == b:
        return direct
    return max(direct, SequenceMatcher(None, pa, pb).ratio())


def _grade_values(text: str) -> List[str]:
    """Все РАЗНЫЕ оценки, упомянутые в тексте (и цифрами, и словами). Порядок сохраняем."""
    t = _norm(text)
    found = []
    #Цифры: любые числа — чтобы поймать и «6», «1» (вне шкалы → отдельная проверка).
    for m in re.findall(r"\b(\d{1,2})\b", t):
        if m not in found:
            found.append(m)
    #Слова-оценки.
    for w in t.split():
        d = _GRADE_BY_WORD.get(w) or _GRADE_BY_WORD.get(_stem(w))
        if d and d not in found:
            found.append(d)
    return found


def _absence_kind(text: str) -> str:
    """Тип пропуска по ключевым основам или '' если пропуск не упомянут. Приоритет:
    уважительная > болезнь > неуважительная (болезнь и уваж. — частные случаи Н)."""
    t = _norm(text)
    if any(k in t for k in _ABSENCE_O):
        return "absent_o"
    if any(k in t for k in _ABSENCE_B):
        return "absent_b"
    if any(k in t for k in _ABSENCE_N):
        return "absent_n"
    return ""


def _has_present(text: str) -> bool:
    t = _norm(text)
    return any(k in t for k in _PRESENT)


def _match_students(text: str, roster: List[Tuple[str, str]],
                    threshold: float = 0.74):
    """Возвращает (student|None, candidates, confidence, multi_flag).

    multi_flag=True — похоже, названо НЕСКОЛЬКО РАЗНЫХ студентов (разные фамилии сильно
    совпали с разными словами) → безопаснее переспросить. candidates — однофамильцы для
    ручного выбора. Никаких выдуманных имён: сопоставляем только с реальным ростером."""
    words = [w for w in _norm(text).split() if len(w) >= 3]
    if not words or not roster:
        return None, [], 0.0, False

    scored = []
    for (f, n) in roster:
        fst = _stem(f)
        best = max((_similar(_stem(w), fst) for w in words), default=0.0)
        scored.append((best, f, n))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[0][0]
    if top < threshold:
        return None, [], top, False

    #Разные фамилии, сильно совпавшие → возможно, названо несколько студентов.
    strong_surnames = {f for (sc, f, n) in scored if sc >= threshold}
    multi = len(strong_surnames) > 1 and (scored[0][0] - _second_surname_score(scored)) < 0.08

    near = [(f, n) for (sc, f, n) in scored if sc >= top - 0.02]
    if len(near) == 1:
        return near[0], [], top, multi

    #Однофамильцы: доразбор по имени. Слово, которым распозналась ФАМИЛИЯ, исключаем —
    #иначе «Иванову» само похоже на «Иван».
    fam_stem = _stem(near[0][0])
    name_words = [w for w in words if _similar(_stem(w), fam_stem) < top - 0.05]
    by_name = []
    for (f, n) in near:
        nst = _stem(n)
        sc = max((_similar(_stem(w), nst) for w in name_words), default=0.0)
        by_name.append((sc, f, n))
    by_name.sort(key=lambda x: x[0], reverse=True)
    if by_name[0][0] >= threshold and (len(by_name) == 1 or by_name[0][0] - by_name[1][0] > 0.1):
        return (by_name[0][1], by_name[0][2]), [], top, False
    return None, near, top, False


def _second_surname_score(scored) -> float:
    """Скор лучшего кандидата с ДРУГОЙ фамилией (для флага «несколько студентов»)."""
    top_f = scored[0][1]
    for (sc, f, _n) in scored:
        if f != top_f:
            return sc
    return 0.0


def parse(text: str, roster: List[Tuple[str, str]],
          today_lessons: List[dict]) -> ParsedCommand:
    """Разбирает команду преподавателя. roster — [(фамилия, имя), ...] ТЕКУЩЕЙ группы;
    today_lessons — занятия текущих группы+предмета за сегодня: [{"id","label"}].

    Любую неоднозначность считаем ошибкой ввода, а не поводом угадать."""
    heard = (text or "").strip()
    base = ParsedCommand(heard=heard)
    if not heard:
        base.error = "Не расслышал команду — повторите чётче."
        return base

    #── 0. ВОПРОС или КОМАНДА? Маркеры вопроса имеют приоритет: при них ничего не пишем,
    #а отдаём текст в обычный Q&A Вектора. Так «сколько пропусков у Гордеева» не станет
    #ошибочной простановкой пропуска. ──────────────────────────────────────────────────
    if any(m in _norm(heard) or m in heard.lower() for m in _QUESTION_MARKERS):
        base.is_question = True
        return base

    #── 1. Действие и значение с ПРОВЕРКОЙ КОНФЛИКТОВ ───────────────────────────────
    grades = _grade_values(text)
    in_scale = [g for g in grades if g in ("2", "3", "4", "5")]
    out_scale = [g for g in grades if g not in ("2", "3", "4", "5")]
    absence = _absence_kind(text)

    #Конфликт: и оценка, и пропуск в одной фразе — не угадываем, что важнее.
    if in_scale and absence:
        base.error = ("В команде и оценка, и пропуск — скажите что-то одно "
                      "(например «Иванову пять» или «Иванов пропуск»).")
        return base
    #Конфликт: несколько РАЗНЫХ оценок.
    if len(in_scale) > 1:
        base.error = (f"Услышал несколько оценок ({', '.join(in_scale)}) — "
                      "повторите одну.")
        return base
    #Оценка вне шкалы (услышал «шесть», «один», «десять»…).
    if out_scale and not in_scale and not absence and not _has_present(text):
        base.error = (f"Оценка «{out_scale[0]}» вне шкалы 2–5 — повторите оценку.")
        return base

    if absence:
        action = absence
        value = {"absent_n": "Н", "absent_b": "Б", "absent_o": "О"}[absence]
    elif in_scale:
        action, value = "grade", in_scale[0]
    elif _has_present(text):
        action, value = "present", "✓"
    else:
        base.error = ("Не понял действие. Скажите оценку (2–5) или "
                      "«пропуск» / «болеет» / «по уважительной» / «был на паре».")
        return base

    #── 2. Студент (нечёткое совпадение с реальным ростером) ───────────────────────
    student, candidates, conf, multi = _match_students(text, roster)
    base.action, base.value, base.confidence = action, value, conf
    if multi:
        base.error = ("Похоже, названо несколько студентов — назовите одного "
                      "(фамилию, при необходимости имя).")
        return base
    #Фамилия не распозналась → пробуем обращение по УНИКАЛЬНОМУ ИМЕНИ. Бурятские имена
    #(«Бато», «Арюна», «Аюр») различимее фамилий, и препод часто зовёт студента по имени.
    #Тот же приём, что в пакетном разборе (_resolve_word_student); порог строгий, поэтому
    #ложно чужого не подставит.
    if student is None and not candidates:
        for w in _norm(text).split():
            if len(w) >= 3:
                by_name = _match_firstname_unique(w, roster)
                if by_name is not None:
                    student = by_name
                    break
    if student is None and not candidates:
        base.error = ("Не узнал студента в этой группе. Повторите фамилию (или имя) "
                      "чётче или выберите студента вручную.")
        return base

    #── 3. Занятие за сегодня ───────────────────────────────────────────────────────
    if not today_lessons:
        base.candidates = candidates
        base.error = ("За сегодня по этому предмету занятий нет — добавьте занятие "
                      "или выберите его вручную.")
        return base
    if len(today_lessons) > 1:
        base.candidates = candidates
        base.error = ("Сегодня несколько занятий — уточните, за какое (скажите тип и "
                      "номер) или выберите вручную.")
        return base
    lesson = today_lessons[0]
    base.lesson_id = lesson.get("id", "")
    base.lesson_label = lesson.get("label", "")

    #── 4. Однофамильцы → выбор студента в диалоге (команда почти готова) ───────────
    if candidates and student is None:
        base.candidates = candidates
        base.summary = f"{_ACTION_RU.get(action, action)} «{value}» за {base.lesson_label}"
        base.error = "Несколько студентов с такой фамилией — выберите нужного."
        return base

    f, n = student
    who = f"{f} {n}".strip()
    base.ok = True
    base.student = student
    base.summary = f"{who}: {_ACTION_RU.get(action, action)} «{value}» за {base.lesson_label}"
    return base


#Ориентиры бурятской фонетики для Whisper: типичные ОСНОВЫ и целые фамилии/имена региона.
#Не привязаны к конкретной группе — просто смещают модель к правильному звучанию, чтобы
#«Гындынова» не превратилась в «Гундинова», а «Арюна» в «Арина». Роняем в initial_prompt
#вместе с реальным ростером (он всегда важнее — стоит последним, ближе к речи).
_BURYAT_HINT = (
    "Дамбаева, Гындынова, Самбуева, Цыренова, Дондоков, Батоева, Жамьянова, "
    "Раднаева, Дашиев, Очиров, Бадмаев, Аюшеева, Доржиева, Будаев, Найданова, "
    "Тугаринова, Цыбикова, Ринчинов, Гомбоев, Шойдоков; Бато, Арюна, Аюр, Саяна, "
    "Баир, Соёл, Оюна, Доржо, Туяна, Чимит, Дулма, Жаргал, Намжил, Сэсэг"
)


def stt_context(roster: List[Tuple[str, str]]) -> str:
    """Подсказка для Whisper (initial_prompt): реальные ФИО + ключевые слова темы + опоры
    бурятской фонетики. Смещает распознавание к настоящим фамилиям и терминам журнала —
    повышает точность в шуме и на редких (в т.ч. бурятских) именах.

    Порядок важен: сначала общие термины и бурятские опоры, а РЕАЛЬНЫЙ ростер — в самом
    конце, ближе к распознаваемой речи (последние слова промпта модель учитывает сильнее)."""
    names = ", ".join(f"{f} {n}".strip() for (f, n) in (roster or []))
    return ("Журнал успеваемости колледжа. Оценки: два, три, четыре, пять, "
            "двойка, тройка, четвёрка, пятёрка, отлично, хорошо, удовлетворительно, "
            "неудовлетворительно. Посещаемость: пропуск, прогулял, болеет, заболел, "
            "по уважительной причине, отпросился, был на паре, присутствовал. "
            "Команды преподавателя: поставь Иванову пять, отметь Петрову пропуск, "
            "всей группе четыре, первым пяти по списку тройку, создай сегодня лекцию "
            "по теме, добавь практику. "
            f"Возможные фамилии и имена: {_BURYAT_HINT}. "
            f"Студенты этой группы: {names}.")


# ═══════════════════════════════════════════════════════════════════════════════════
# ПАКЕТНЫЕ КОМАНДЫ и СОЗДАНИЕ ЗАНЯТИЯ (несколько студентов / вся группа / первые N)
# ═══════════════════════════════════════════════════════════════════════════════════

#Числительные словами → int (для «первые десять …»).
_CARDINAL = {
    "один": 1, "одному": 1, "два": 2, "двум": 2, "двоим": 2, "трех": 3, "трём": 3,
    "троим": 3, "три": 3, "четыре": 4, "четырем": 4, "четырём": 4, "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8, "девять": 9,
    "девяти": 9, "десять": 10, "десяти": 10, "одиннадцать": 11, "двенадцать": 12,
    "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20,
    "двадцати": 20, "тридцать": 30,
}

#«Вся группа» — целим во всех студентов ростера.
_ALL_GROUP = ("всей группе", "всю группу", "вся группа", "всем студентам", "всем ученикам",
              "всему классу", "весь класс", "всему потоку", "всем поставь", "всем ставь",
              "всем выставь", "всем по", "каждому", "каждому студенту", "все получили",
              "все получают", "поголовно", "всем без исключения", "всей подгруппе",
              "группе поставь", "группе ставь", "классу поставь", "всем ", "всех ")

#Триггеры создания занятия и типы.
_LESSON_CREATE = ("созда", "добавь занят", "добавь лекц", "добавь практ", "добавь семинар",
                  "новое занят", "новую лекц", "новую практ", "проведи", "запиши занят",
                  "поставь занят", "заведи занят", "запланируй занят")
_LESSON_TYPES = [("лаборатор", "Лабораторная"), ("практик", "Практика"),
                 ("лекци", "Лекция"), ("семинар", "Семинар"), ("экзамен", "Экзамен"),
                 ("зачет", "Зачёт")]


@dataclass
class WriteItem:
    surname: str = ""
    name: str = ""
    action: str = ""          #grade | present | absent_n | absent_b | absent_o
    value: str = ""           #«5» | «✓» | «Н» | «Б» | «О»

    @property
    def who(self) -> str:
        return f"{self.surname} {self.name}".strip()


@dataclass
class LessonPlan:
    type: str = "Лекция"
    topic: str = ""
    number: int = 0           #0 — авто-нумерация вызывающим кодом


@dataclass
class BatchResult:
    kind: str = "error"       #grades | lesson | question | error
    is_question: bool = False
    items: List[WriteItem] = field(default_factory=list)   #для kind=grades
    lesson: Optional[LessonPlan] = None                    #для kind=lesson
    lesson_id: str = ""
    lesson_label: str = ""
    error: str = ""
    warnings: List[str] = field(default_factory=list)      #мягкие проблемы (кого пропустили)
    heard: str = ""


def _norm_words(text: str) -> List[str]:
    return [w for w in _norm(text).split() if w]


def _grade_at_word(w: str) -> Optional[str]:
    """Оценка 2–5 из одного слова (цифрой или словом), иначе None. Вне шкалы → None."""
    if w in ("2", "3", "4", "5"):
        return w
    d = _GRADE_BY_WORD.get(w) or _GRADE_BY_WORD.get(_stem(w))
    return d if d in ("2", "3", "4", "5") else None


def _first_n(text: str) -> Optional[int]:
    """Число из «первые N / первым N / N человек по списку / по алфавиту». None — не про N."""
    t = _norm(text)
    if not any(k in t for k in ("перв", "по списку", "по алфавит", "сначала", "первых")):
        #«N человек» без «первые/по списку» не считаем — слишком двусмысленно.
        if "человек" not in t and "студент" not in t:
            return None
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    for w in t.split():
        if w in _CARDINAL:
            return _CARDINAL[w]
    return None


def _match_firstname_unique(word: str, roster: List[Tuple[str, str]],
                            threshold: float = 0.80):
    """Уникальное совпадение по ИМЕНИ (для обращения «Бато не пришёл», «Арюне пять»).
    Возвращает студента ТОЛЬКО если ровно один по имени и он заметно лучше остальных —
    иначе None (имена менее уникальны, чем фамилии, поэтому строже)."""
    ws = _stem(word)
    if len(ws) < 3:
        return None
    scored = sorted(((_similar(_stem(n), ws), f, n) for (f, n) in roster),
                    key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.1:
        return None   #несколько с похожим именем — не угадываем
    return (scored[0][1], scored[0][2])


def _resolve_word_student(words: List[str], i: int, roster: List[Tuple[str, str]]):
    """Кого назвали словом words[i] (+ возможно соседнее имя). Возвращает
    (student|None, candidates, matched_len). matched_len — сколько слов «съедено» (1 или 2)."""
    w = words[i]
    if len(w) < 3:
        return None, [], 1
    student, cands, conf, _multi = _match_students(w, roster)
    if student is not None:
        return student, [], 1
    if cands:
        #Однофамильцы — пробуем доразобрать по соседнему слову (имя): справа, затем слева.
        for j in (i + 1, i - 1):
            if 0 <= j < len(words):
                st2, c2, _cf, _m = _match_students(w + " " + words[j], roster)
                if st2 is not None:
                    return st2, [], (2 if j == i + 1 else 1)
        return None, cands, 1
    #Фамилия не подошла — вдруг назвали по ИМЕНИ (уникальному). Напр. бурятские «Бато»,
    #«Арюна» как обращение.
    st_fn = _match_firstname_unique(w, roster)
    if st_fn is not None:
        return st_fn, [], 1
    return None, [], 1


def _lesson_from_text(heard: str) -> LessonPlan:
    """Разбирает «Создай сегодня лекцию по теме Введение в модули» → LessonPlan.
    Тему берём из ОРИГИНАЛЬНОГО текста (сохраняем регистр)."""
    low = _norm(heard)
    ltype = "Лекция"
    for stem, name in _LESSON_TYPES:
        if stem in low:
            ltype = name
            break
    number = 0
    m = re.search(r"номер\s+(\d{1,3})", low) or re.search(r"№\s*(\d{1,3})", heard)
    if m:
        number = int(m.group(1))
    #Тема: после «по теме / на тему / тема / по» до конца. Ищем в ОРИГИНАЛЕ.
    topic = ""
    for marker in ("по теме", "на тему", "тема", "теме", "по"):
        mm = re.search(marker + r"\s+(.+)$", heard, flags=re.IGNORECASE)
        if mm:
            topic = mm.group(1).strip(" .,:;")
            break
    return LessonPlan(type=ltype, topic=topic, number=number)


def _assign_lesson(base: BatchResult, today_lessons: List[dict]) -> bool:
    """Проставляет base.lesson_id/label по занятию за сегодня. False + base.error — если
    занятий нет или их несколько (нужно уточнить)."""
    if not today_lessons:
        base.error = ("За сегодня по этому предмету занятий нет — сначала создайте занятие "
                      "(«создай сегодня лекцию по теме …») или выберите его вручную.")
        return False
    if len(today_lessons) > 1:
        base.error = "Сегодня несколько занятий — уточните, за какое, или выберите вручную."
        return False
    base.lesson_id = today_lessons[0].get("id", "")
    base.lesson_label = today_lessons[0].get("label", "")
    return True


def parse_batch(text: str, roster: List[Tuple[str, str]],
                today_lessons: List[dict]) -> BatchResult:
    """Разбирает команду преподавателя, В ТОМ ЧИСЛЕ пакетную:
      • вопрос                         → kind=question (в обычный Q&A);
      • «создай сегодня лекцию …»       → kind=lesson;
      • «всей группе пять»              → kind=grades, всем студентам;
      • «первым десяти по списку пять»  → kind=grades, первым N по алфавиту;
      • «Иванову 5, Петрову 4»          → kind=grades, по позициям (ближайшая оценка справа);
      • «Иванову и Петрову пять»        → kind=grades, одна оценка на всех названных;
      • одиночная команда               → kind=grades с одним элементом.
    Любую неоднозначность → warnings (кого пропустили) или error. Никаких выдуманных имён.
    Итог ВСЕГДА подтверждается преподавателем (список правок в диалоге)."""
    heard = (text or "").strip()
    base = BatchResult(heard=heard)
    if not heard:
        base.error = "Не расслышал команду — повторите чётче."
        return base

    low = _norm(heard)

    #── Создание занятия (проверяем ДО вопросов: «создай…» не вопрос) ──────────────────
    if any(t in low for t in _LESSON_CREATE) and any(s in low for s, _ in _LESSON_TYPES):
        plan = _lesson_from_text(heard)
        base.kind = "lesson"
        base.lesson = plan
        if not plan.topic:
            base.warnings.append("Тема не распознана — уточните в диалоге.")
        return base

    #── Вопрос? (маркеры имеют приоритет: ничего не пишем, отдаём в Q&A) ───────────────
    if any(m in low or m in heard.lower() for m in _QUESTION_MARKERS):
        base.is_question = True
        base.kind = "question"
        return base

    words = _norm_words(heard)

    #── Значения: оценки (с позициями) и вид пропуска (глобально) ──────────────────────
    grade_pos = [(i, g) for i, w in enumerate(words) for g in [_grade_at_word(w)] if g]
    #цифры вне шкалы — явная ошибка, а не «нет оценки»
    out_scale = [w for w in words if re.fullmatch(r"\d{1,2}", w) and w not in ("2", "3", "4", "5")]
    absence = _absence_kind(heard)
    present = _has_present(heard) and not absence and not grade_pos

    def _val_for(action_val):
        return action_val

    #── Цель: вся группа / первые N / поимённо ────────────────────────────────────────
    all_group = any(k in low for k in _ALL_GROUP)
    n_first = _first_n(heard)

    #Одно значение для «всей группы»/«первых N» (там значение общее).
    def _single_value(gp):
        if absence:
            return absence, {"absent_n": "Н", "absent_b": "Б", "absent_o": "О"}[absence]
        if present:
            return "present", "✓"
        grades = sorted({g for _, g in gp})
        if len(grades) == 1:
            return "grade", grades[0]
        return None, None   #ноль или несколько разных — ошибка

    if all_group or n_first is not None:
        #Счётчик N (напр. «первым 3») мог попасть в оценки как цифра 2–5 — исключаем его.
        gp_val = grade_pos
        if n_first is not None:
            for k, (gi, _g) in enumerate(grade_pos):
                if words[gi] == str(n_first):
                    gp_val = grade_pos[:k] + grade_pos[k + 1:]
                    break
        action, value = _single_value(gp_val)
        if action is None:
            if out_scale:
                base.error = f"Оценка «{out_scale[0]}» вне шкалы 2–5 — повторите."
            elif len({g for _, g in grade_pos}) > 1:
                base.error = "Для всей группы назвали несколько разных оценок — повторите одну."
            else:
                base.error = "Не понял, что ставить всем — оценку (2–5) или пропуск."
            return base
        target = list(roster)
        target.sort(key=lambda s: (_norm(s[0]), _norm(s[1])))   #по алфавиту (фамилия, имя)
        if n_first is not None:
            if n_first <= 0:
                base.error = "Сколько первых студентов? Повторите число."
                return base
            target = target[:n_first]
        if not target:
            base.error = "В группе нет студентов."
            return base
        if not _assign_lesson(base, today_lessons):
            return base
        base.kind = "grades"
        base.items = [WriteItem(f, n, action, value) for (f, n) in target]
        return base

    #── Поимённо: собираем фамилии с позициями, присваиваем значения ──────────────────
    found = []   #(idx, student)
    i = 0
    while i < len(words):
        if _grade_at_word(words[i]) or words[i] in _CARDINAL:
            i += 1
            continue
        student, cands, eaten = _resolve_word_student(words, i, roster)
        if student is not None:
            found.append((i, student))
            i += eaten
            continue
        if cands:
            base.warnings.append(f"«{words[i]}» — несколько однофамильцев, пропустил "
                                 f"(поставьте отдельно с именем).")
        i += 1

    if not found:
        if base.warnings:   #были однофамильцы — подсказываем назвать с именем
            base.error = ("Есть однофамильцы — назовите студента вместе с именем, "
                          "например «Дашиеву Аюру пять».")
        else:
            base.error = ("Не узнал фамилий студентов в этой группе. Повторите чётче "
                          "или поставьте вручную.")
        return base

    #Значение каждому: пропуск/присутствие — одно на всех названных; оценки — по позиции.
    items = []
    if absence or present:
        action = absence or "present"
        value = {"absent_n": "Н", "absent_b": "Б", "absent_o": "О", "present": "✓"}[action]
        if grade_pos:
            base.error = ("В команде и оценка, и посещаемость — скажите что-то одно.")
            return base
        items = [WriteItem(f, n, action, value) for _, (f, n) in found]
    elif grade_pos:
        gp = sorted(grade_pos)
        only_one = len({g for _, g in gp}) == 1
        for idx, (f, n) in found:
            if only_one:
                val = gp[0][1]
            else:
                nxt = next((g for gi, g in gp if gi > idx), None)
                if nxt is None:
                    base.warnings.append(f"{f} {n} — не назвали оценку, пропустил.")
                    continue
                val = nxt
            items.append(WriteItem(f, n, "grade", val))
    else:
        if out_scale:
            base.error = f"Оценка «{out_scale[0]}» вне шкалы 2–5 — повторите."
        else:
            base.error = ("Не понял действие. Скажите оценку (2–5), «пропуск»/«болеет»/"
                          "«по уважительной» или «был на паре».")
        return base

    if not items:
        base.error = ("Не удалось сопоставить студентов с оценками — повторите по образцу "
                      "«Иванову пять, Петрову четыре».")
        return base
    if not _assign_lesson(base, today_lessons):
        return base
    base.kind = "grades"
    base.items = items
    return base
