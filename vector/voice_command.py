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
    "2": {"два", "две", "двойку", "двойка", "двойки", "неуд", "неудовлетворительно",
          "неудовлетворительная", "неуды"},
    "3": {"три", "тройку", "тройка", "тройки", "удовлетворительно", "удов",
          "удовлетворительная"},
    "4": {"четыре", "четверку", "четверка", "четверки", "хорошо", "хор", "хорошая"},
    "5": {"пять", "пятерку", "пятерка", "пятерки", "отлично", "отл", "отличная",
          "превосходно"},
}
#Обратный индекс слово→цифра.
_GRADE_BY_WORD = {w: d for d, ws in _WORD_GRADE.items() for w in ws}

#Ключевые ОСНОВЫ для посещаемости (ищем вхождением — ловит склонения/спряжения).
_ABSENCE_O = ("уважительн", "по уважит", "освобожд", "отпросил", "с разрешения",
              "по справке", "справка")
_ABSENCE_B = ("болеет", "болел", "больнич", "по болезни", "болезн", "заболел",
              "температур", "на больнич")
_ABSENCE_N = ("пропуск", "прогул", "отсутств", "не был", "не была", "не были",
              "не пришел", "не пришла", "не явил", "неявк", "прогулял", "проспал",
              "не появил", "отсутствовал")
#Присутствие (лекция ✓). ВНИМАНИЕ: проверяется ПОСЛЕ негативов, иначе «не пришёл»
#ложно распознается как «пришёл».
_PRESENT = ("присутств", "был на", "была на", "были на", "на месте", "на паре",
            "на лекции", "на занятии", "пришел", "пришла", "явил", "отметь присут",
            "отметь как присут")

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


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


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
    for (sc, f, n) in scored:
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
    if student is None and not candidates:
        base.error = ("Не узнал фамилию студента в этой группе. Повторите фамилию "
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


def stt_context(roster: List[Tuple[str, str]]) -> str:
    """Подсказка для Whisper (initial_prompt): реальные ФИО + ключевые слова темы. Смещает
    распознавание к настоящим фамилиям и терминам журнала — повышает точность в шуме."""
    names = ", ".join(f"{f} {n}".strip() for (f, n) in (roster or []))
    return ("Журнал успеваемости. Оценки: два, три, четыре, пять. "
            "Посещаемость: пропуск, болеет, по уважительной, был на паре. "
            f"Студенты группы: {names}.")
