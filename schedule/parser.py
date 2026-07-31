"""
schedule/parser.py — загрузка и разбор расписания колледжа с portal.esstu.ru.

Поток данных (см. внутренний план): клиент сам тянет ПУБЛИЧНЫЙ статический сайт
расписания и разбирает его в модель (model.py). На сервер/в синхронизацию это не
уходит — снимок кладётся в локальный зашифрованный кэш (store.py). GET'ы read-only,
персональные данные на сайт не отправляем — 152-ФЗ тут не задет.

Особенности сайта, из-за которых код такой, какой есть:
  • Кодировка страниц — windows-1251 (выставляем resp.encoding вручную).
  • HTML сгенерирован Word 97: теги вперемешку, <P> без закрытия, лишние <FONT>.
    Поэтому разбираем стандартным html.parser как поток «строка таблицы → ячейки»,
    а не пытаемся строить дерево.
  • Колледж = группы, чьё имя начинается на «К» (в сегменте /spezialitet/). «М…» —
    магистратура, её отбрасываем.
  • Страница группы: строка «Пары» (1-я..6-я), строка «Время», затем 12 строк-дней
    (6 дней неделя I + 6 дней неделя II). Границу недель ловим по повтору «Пнд».
  • Ячейка пары: «тип.Предмет ФАМИЛИЯ И.О.  а.Аудитория» либо «_» (пусто). Бывают
    подгруппы и сноски — их кладём в Lesson.extra, а сырой текст всегда в Lesson.raw.

Зависимости: только stdlib + requests (уже в проекте). Никакого BeautifulSoup —
лицензии должны оставаться чистыми (проект продаётся).
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from html import unescape

import requests

from .model import (
    Lesson, GroupSchedule, Snapshot, WEEKDAYS, DEFAULT_PAIR_TIMES,
)

#База сайта и РЕЕСТР категорий расписания (см. portal.esstu.ru/menu.htm — там
#пять ссылок «Расписание занятий студентов», четыре ведут на списки групп в
#этом же формате сайта, пятая — «Календарный учебный график» — на ДРУГОЙ домен
#и таблицу с датами семестров, не список групп, поэтому в реестр не входит).
BASE_URL = "https://portal.esstu.ru/"

#dated=True — «сессионный» формат страницы группы (заголовки дней — конкретные
#календарные даты «Пнд,06 апреля», а не «Пнд»/«Втр»; см. parse_group_page_dated).
#prefix=None — на странице этой категории нет посторонних групп, фильтровать
#по первой букве имени не нужно (в отличие от spezialitet/, где вперемешку с
#колледжем идёт магистратура).
CATEGORIES: dict[str, dict] = {
    "college": {
        "label": "Магистратура, колледж, ДОУ",
        "dir": "spezialitet/",
        "prefix": "К",
        "dated": False,
    },
    "bakalavriat": {
        "label": "Бакалавриат, специалитет",
        "dir": "bakalavriat/",
        "prefix": None,
        "dated": False,
    },
    "zo1": {
        "label": "Заочное 1",
        "dir": "zo1/",
        "prefix": None,
        "dated": True,
    },
    "zo2": {
        "label": "Заочное 2",
        "dir": "zo2/",
        "prefix": None,
        "dated": True,
    },
}
DEFAULT_CATEGORY = "college"

#Старые имена — производные от реестра, чтобы ничего из уже существующего кода
#(store.py, schedule_web.py, тесты) не сломалось при переходе на CATEGORIES.
COLLEGE_DIR = CATEGORIES[DEFAULT_CATEGORY]["dir"]
COLLEGE_INDEX = BASE_URL + COLLEGE_DIR + "raspisan.htm"

#Группы колледжа начинаются на кириллическую «К» (не латинскую). Имена бывают
#с дробями и запятыми: К15/1, К14,15.0, К112/2,113.02 — поэтому критерий простой:
#первый значимый символ имени = «К».
_COLLEGE_PREFIX = CATEGORIES[DEFAULT_CATEGORY]["prefix"]

#Тип занятия в начале ячейки: «лек.», «пр.», «лаб.» (точка обязательна).
_KIND_RE = re.compile(r"^\s*(лек|пр|лаб|сем|конс|зач|экз)\.\s*", re.IGNORECASE)

#Аудитория: «а.<токен>» до пробела. Реальные номера без пробелов внутри
#(«0310», «15-463и/д», «9-Спорт2»). Берём первую — вторая (подгруппа) уйдёт в extra.
_ROOM_RE = re.compile(r"а\.(\S+)")

#ФАМИЛИЯ И.О. — фамилия заглавными (≥2 буквы), затем 1-2 инициала с точками.
#Пример: «ШАГДУРОВА А.И.», «КИМ С.В.». Кириллица + возможный дефис в фамилии.
_TEACHER_RE = re.compile(
    r"([А-ЯЁ][А-ЯЁ\-]{1,}(?:\s+[А-ЯЁ][А-ЯЁ\-]+)?)\s+([А-ЯЁ]\.\s?[А-ЯЁ]?\.?)"
)

#То же самое, но фамилия ОБЫЧНЫМ регистром (заглавная первая буква, дальше
#строчные) — так пишут преподавателя на сессионных страницах (Заочное 1/2):
#«Прудова Л.Ю.», не «ПРУДОВА Л.Ю.». Проверено живым разбором zo1/1.htm —
#используется ТОЛЬКО в parse_group_page_dated, не в общем parse_cell по
#умолчанию, чтобы не плодить ложные срабатывания на обычных страницах.
#⚠️ БЕЗ «второго слова фамилии» (в отличие от _TEACHER_RE выше): многие реальные
#предметы — само по себе одно капитализированное слово («Химия», «История»,
#«Физика»), и опциональное продолжение ловило бы СЛЕДУЮЩЕЕ слово (настоящую
#фамилию) как «вторую часть фамилии», сдвигая границу предмета в 0 символов —
#поймано тестом test_group_schedule_dated_category_end_to_end на «Химия Петров
#П.П.» (без этого урезания фамилия «съедала» весь предмет). Одиночных
#Title-Case фамилий из двух слов в реальных данных не встречено.
_TEACHER_RE_DATED = re.compile(
    r"([А-ЯЁ][а-яё\-]{2,})\s+([А-ЯЁ]\.\s?[А-ЯЁ]?\.?)"
)


def fetch_text(url: str, timeout: int = 20) -> str:
    """Скачивает страницу и декодирует из windows-1251.

    TLS-проверка включена (verify=True) — это публичный сайт, свой CA не нужен.
    Кодировку выставляем явно: requests по «Content-Type» иногда угадывает неверно.
    """
    resp = requests.get(url, timeout=timeout, verify=True,
                        headers={"User-Agent": "GradeBookAI/2.7 schedule-sync"})
    resp.raise_for_status()
    resp.encoding = "windows-1251"
    return resp.text


class _TableRowParser(HTMLParser):
    """Собирает таблицу как список строк, где строка — список текстов ячеек.

    Word-генерированный HTML непредсказуем, поэтому идём потоком: на <tr> начинаем
    строку, на <td> — ячейку, накапливаем текст до следующей ячейки/строки. <br>
    превращаем в пробел. Внутреннюю разметку (<font>, <b>, <p>) просто игнорируем —
    нам нужен только текст.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "tr":
            #новая строка; недозакрытую предыдущую сбрасываем в результат
            if self._row is not None:
                self._flush_cell()
                self.rows.append(self._row)
            self._row = []
            self._cell = None
        elif t == "td":
            if self._row is None:
                self._row = []
            self._flush_cell()
            self._cell = []
        elif t == "br":
            if self._cell is not None:
                self._cell.append(" ")

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "tr" and self._row is not None:
            self._flush_cell()
            self.rows.append(self._row)
            self._row = None
        #</td> не закрываем принудительно: следующий <td>/<tr> сам сбросит ячейку.

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def _flush_cell(self):
        if self._cell is not None and self._row is not None:
            text = unescape("".join(self._cell))
            #схлопываем пробелы, но сохраняем сам факт непустоты
            text = re.sub(r"\s+", " ", text).strip()
            self._row.append(text)
        self._cell = None

    def close(self):
        super().close()
        if self._row is not None:
            self._flush_cell()
            self.rows.append(self._row)
            self._row = None


def _extract_rows(html: str) -> list[list[str]]:
    p = _TableRowParser()
    p.feed(html)
    p.close()
    return p.rows


def parse_cell(text: str, pair_no: int = 0, time: str = "",
              teacher_re: re.Pattern = _TEACHER_RE) -> Lesson | None:
    """Разбирает текст одной клетки в Lesson. Пустая клетка («_») → None.

    Разбор best-effort: сначала срезаем тип («лек.»), потом вытаскиваем аудиторию и
    преподавателя, остаток считаем названием предмета. Что не уложилось — в extra.
    Сырой текст всегда сохраняем в raw.

    teacher_re — сессионные страницы (Заочное) пишут фамилию НЕ капсом
    («Прудова Л.Ю.», а не «ШАГДУРОВА А.И.» как везде остальном) —
    parse_group_page_dated передаёт свой вариант регулярки, не трогая дефолт
    (чтобы не плодить ложные срабатывания на обычных страницах, где регистр
    внутри названия предмета — единственный сигнал «это не фамилия»)."""
    raw = (text or "").strip()
    #«Окно» — «_», но на сессионных страницах (Заочное) слипшиеся ячейки иногда
    #дают «_ _»/«_  _» вместо одной «_» — тоже пусто, не реальный текст занятия.
    if not raw or not raw.strip("_ "):
        return None

    rest = raw
    kind = ""
    m = _KIND_RE.match(rest)
    if m:
        kind = m.group(1).lower()
        rest = rest[m.end():]

    #Аудитория(и): первая «а.…». Возможны две (подгруппы) — вторую отправим в extra.
    room = ""
    rooms = _ROOM_RE.findall(rest)
    if rooms:
        room = rooms[0].strip()

    #Преподаватель: первый «Фамилия И.О.». Из остатка вырезаем найденного
    #преподавателя и аудиторию, чтобы получить чистое название предмета.
    teacher = ""
    tm = teacher_re.search(rest)
    if tm:
        teacher = re.sub(r"\s+", " ", f"{tm.group(1)} {tm.group(2)}").strip()

    subject = rest
    if tm:
        #предмет — это то, что ДО фамилии преподавателя
        subject = rest[:tm.start()].strip()
    #убираем «а.…» из предмета, если фамилии не было и аудитория попала в subject
    subject = _ROOM_RE.sub("", subject).strip()
    subject = subject.strip(" .-—")

    #«extra» — всё, что идёт после первого преподавателя (вторая подгруппа/сноска).
    extra = ""
    if tm:
        tail = rest[tm.end():].strip()
        #отрежем аудиторию первой подгруппы из начала хвоста
        tail = _ROOM_RE.sub("", tail, count=1).strip(" .-—")
        if tail:
            extra = tail

    return Lesson(pair_no=pair_no, time=time, kind=kind, subject=subject,
                  teacher=teacher, room=room, raw=raw, extra=extra)


def _find_pair_times(rows: list[list[str]], max_pairs: int = 6) -> list[str]:
    """Ищет строку «Время» и возвращает интервалы (фолбэк — DEFAULT_PAIR_TIMES).

    max_pairs=8 — сессионные страницы (Заочное) размечают до 8 пар в день,
    обычные (колледж/бакалавриат) — 6."""
    for row in rows:
        if row and row[0].strip().lower().startswith("время"):
            times = [c.strip() for c in row[1:] if c.strip()]
            #оставляем только похожее на интервал ЧЧ:ММ-ЧЧ:ММ
            times = [t for t in times if re.match(r"\d{1,2}:\d{2}", t)]
            if times:
                return times[:max_pairs]
    return list(DEFAULT_PAIR_TIMES)


def parse_group_page(html: str, name: str = "", href: str = "") -> GroupSchedule:
    """Разбирает страницу группы (N.htm) в GroupSchedule на обе недели.

    Логика разбиения на недели: идём по строкам-дням (первая ячейка ∈ WEEKDAYS).
    Первый блок Пнд..Сбт — неделя I; как только «Пнд» встречается снова — начинается
    неделя II. Так устойчиво и к пропущенным дням.
    """
    rows = _extract_rows(html)
    pair_times = _find_pair_times(rows)

    weeks: dict = {1: {}, 2: {}}
    week = 1
    seen_days_in_week: set[str] = set()

    for row in rows:
        if not row:
            continue
        head = row[0].strip()
        if head not in WEEKDAYS:
            continue
        #повтор дня в той же неделе → переходим на неделю II
        if head in seen_days_in_week:
            week = 2
            seen_days_in_week = set()
        seen_days_in_week.add(head)

        lessons = []
        for i in range(1, min(len(row), 7)):       # до 6 пар
            pair_no = i
            time = pair_times[i - 1] if i - 1 < len(pair_times) else ""
            ls = parse_cell(row[i], pair_no=pair_no, time=time)
            if ls is not None:
                lessons.append(ls)
        if lessons:
            weeks.setdefault(week, {})[head] = lessons

    #пустые недели не держим (если у группы только одна неделя — ну и пусть)
    weeks = {w: days for w, days in weeks.items() if days}
    return GroupSchedule(name=name, href=href, weeks=weeks, pair_times=pair_times)


def category_index_url(category: str = DEFAULT_CATEGORY) -> str:
    cat = CATEGORIES[category]
    return BASE_URL + cat["dir"] + "raspisan.htm"


def category_group_url(category: str, href: str) -> str:
    return BASE_URL + CATEGORIES[category]["dir"] + href


#Заголовок дня на сессионных страницах (Заочное 1/2): «Пнд,06 апреля» — короткий
#день + запятая (без пробела перед ней) + дата. Обычные категории такого не дают.
_WEEKDAY_DATE_RE = re.compile(
    r"^(Пнд|Втр|Срд|Чтв|Птн|Сбт|Вск),\s*(.+)$")


def parse_group_page_dated(html: str, name: str = "", href: str = "") -> GroupSchedule:
    """Разбирает СЕССИОННУЮ страницу группы (Заочное 1/2, `CATEGORIES[...]["dated"]`).

    Отличия от обычной parse_group_page (живая проверка на реальных страницах
    zo1/zo2): заголовок дня — не «Пнд», а «Пнд,06 апреля» (конкретная
    календарная дата, не день недели «вообще»); до 8 пар в день (не 6); строка
    «Пары»/«Время» ПОВТОРЯЕТСЯ перед каждым следующим блоком Пнд..Вск — это и
    есть граница сессионной «недели» (в отличие от parse_group_page, где
    границу ловим по повтору САМОГО дня — здесь день не повторяется НИКОГДА,
    в заголовке всегда уникальная дата, поэтому нужен другой якорь).

    Возвращает ТУ ЖЕ GroupSchedule/Lesson — `weeks[N]` здесь не чётность, а
    порядковый номер сессионного блока (1, 2, 3…), `day` — не «Пнд», а сама
    строка «Пнд, 06 апреля» (её же и показываем в UI как есть)."""
    rows = _extract_rows(html)
    pair_times = _find_pair_times(rows, max_pairs=8)

    weeks: dict = {}
    week = 0
    for row in rows:
        if not row:
            continue
        head = row[0].strip()
        if head.lower().startswith("пары"):
            week += 1
            continue
        m = _WEEKDAY_DATE_RE.match(head)
        if not m:
            continue
        day_label = f"{m.group(1)}, {m.group(2)}"

        lessons = []
        for i in range(1, min(len(row), 9)):        # до 8 пар
            pair_no = i
            time = pair_times[i - 1] if i - 1 < len(pair_times) else ""
            ls = parse_cell(row[i], pair_no=pair_no, time=time,
                           teacher_re=_TEACHER_RE_DATED)
            if ls is not None:
                lessons.append(ls)
        if lessons:
            weeks.setdefault(week or 1, {})[day_label] = lessons

    return GroupSchedule(name=name, href=href, weeks=weeks, pair_times=pair_times)


def list_category_groups(html: str, category: str = DEFAULT_CATEGORY) -> list[tuple[str, str]]:
    """Возвращает [(имя_группы, href)] из индекса категории.

    Индекс — таблица курсов со ссылками <a href="N.htm">Имя</a>. Категории с
    заданным `prefix` (сейчас только college) берут только группы, чьё имя
    начинается с него (spezialitet/ вперемешку содержит и магистратуру);
    остальные категории (bakalavriat/zo1/zo2) отдают все ссылки как есть —
    посторонних групп на их страницах индекса нет."""
    prefix = CATEGORIES[category]["prefix"]
    groups: list[tuple[str, str]] = []
    seen = set()
    #простой разбор якорей: href + текст
    for m in re.finditer(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', html,
                         re.IGNORECASE | re.DOTALL):
        href = m.group(1).strip()
        text = re.sub(r"<[^>]+>", "", m.group(2))
        text = re.sub(r"\s+", " ", unescape(text)).strip()
        if not text or (prefix and not text.startswith(prefix)):
            continue
        if text in seen:
            continue
        seen.add(text)
        groups.append((text, href))
    return groups


def list_college_groups(html: str) -> list[tuple[str, str]]:
    """Совместимость: то же самое, что list_category_groups(html, "college")."""
    return list_category_groups(html, DEFAULT_CATEGORY)


def build_snapshot(category: str = DEFAULT_CATEGORY, progress_cb=None,
                   fetch=fetch_text) -> Snapshot:
    """Полный парс: индекс категории → страницы её групп → агрегация + инверсия.

    Без аргументов — 100% прежнее поведение (категория «колледж»). Тяжёлая
    операция (десятки GET) — вызывать в ФОНОВОМ потоке. progress_cb(done,
    total, name) опционально дёргается по ходу для индикатора прогресса. Параметр
    fetch подменяется в тестах (чтобы не ходить в сеть).
    """
    from datetime import datetime, timezone

    dated = CATEGORIES[category]["dated"]
    page_parser = parse_group_page_dated if dated else parse_group_page

    index_html = fetch(category_index_url(category))
    pairs = list_category_groups(index_html, category)

    snap = Snapshot(updated_at=datetime.now(timezone.utc).isoformat())
    subjects: set[str] = set()
    total = len(pairs)

    for i, (name, href) in enumerate(pairs):
        url = category_group_url(category, href)
        try:
            page = fetch(url)
            gs = page_parser(page, name=name, href=href)
        except Exception as e:
            #одна сбойная группа не должна ронять весь снимок
            if progress_cb:
                progress_cb(i + 1, total, f"{name} (ошибка: {e})")
            continue
        snap.groups[name] = gs
        for subj in gs.subjects():
            subjects.add(subj)
        if not dated and (not snap.pair_times or snap.pair_times == list(DEFAULT_PAIR_TIMES)):
            snap.pair_times = gs.pair_times
        _index_teachers(snap.teacher_index, name, gs)
        if progress_cb:
            progress_cb(i + 1, total, name)

    snap.subjects = sorted(subjects)
    return snap


def _index_teachers(index: dict, group_name: str, gs: GroupSchedule):
    """Инверсия: добавляет пары группы в индекс преподавателей.

    index[teacher][week][day] = [{group, lesson}]. Один преподаватель так собирает
    своё расписание из всех групп колледжа, где он ведёт.
    """
    for week, day, ls in gs.all_lessons():
        if not ls.teacher:
            continue
        t = ls.teacher
        index.setdefault(t, {}).setdefault(week, {}).setdefault(day, []).append(
            {"group": group_name, "lesson": ls})
