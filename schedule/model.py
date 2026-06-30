"""
schedule/model.py — модель данных расписания ВСГУТУ (колледж).

Зачем отдельная модель. Сайт расписания (portal.esstu.ru) отдаёт грязный HTML,
сгенерированный Microsoft Word 97. Парсер (parser.py) превращает его в эти простые
датаклассы, а весь остальной код (UI, кэш, задел под Вектора) работает уже с ними и
не знает про разметку сайта. Любой объект умеет сериализоваться в обычный dict/JSON —
так снимок целиком кладётся в локальный зашифрованный кэш (store.py).

Главный принцип надёжности: у каждой пары мы ВСЕГДА храним исходный текст ячейки
(`raw`). Эвристический разбор на предмет/преподавателя/аудиторию может промахнуться
на нестандартной ячейке (подгруппы, сноски «и/д», «экол» и т.п.) — но показать
пользователю сырой текст мы сможем в любом случае.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

#Дни учебной недели в том же порядке, что на сайте (Сбт включительно — суббота
#у колледжа рабочая). Воскресенья в расписании нет.
WEEKDAYS = ["Пнд", "Втр", "Срд", "Чтв", "Птн", "Сбт"]

#Время пар по умолчанию — фолбэк, если со страницы строку «Время» прочитать не
#удалось. Реальные значения всё равно берём со страницы (они там есть).
DEFAULT_PAIR_TIMES = [
    "09:00-10:35",
    "10:45-12:20",
    "13:00-14:35",
    "14:45-16:20",
    "16:25-18:00",
    "18:05-19:40",
]


@dataclass
class Lesson:
    """Одна пара в одной клетке расписания.

    pair_no — номер пары (1..6). kind — тип занятия («лек»/«пр»/«лаб»/«» если не
    распознан). subject/teacher/room — best-effort разбор. raw — исходный текст
    ячейки (источник правды для показа). extra — «хвост» с подгруппой/сноской,
    который не уложился в основные поля (например, второй преподаватель подгруппы).
    """
    pair_no: int
    time: str = ""
    kind: str = ""
    subject: str = ""
    teacher: str = ""
    room: str = ""
    raw: str = ""
    extra: str = ""

    def is_empty(self) -> bool:
        """Пустая клетка («окно»): на сайте это «_» или пробелы."""
        return not self.raw.strip() or self.raw.strip() == "_"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Lesson":
        return Lesson(
            pair_no=int(d.get("pair_no", 0)),
            time=d.get("time", ""),
            kind=d.get("kind", ""),
            subject=d.get("subject", ""),
            teacher=d.get("teacher", ""),
            room=d.get("room", ""),
            raw=d.get("raw", ""),
            extra=d.get("extra", ""),
        )


@dataclass
class GroupSchedule:
    """Расписание одной учебной группы на обе недели.

    weeks[week][day] = список Lesson за этот день (только непустые пары). week — 1
    или 2 (нечётная/чётная), day — короткое имя из WEEKDAYS.
    """
    name: str
    href: str = ""
    #week (1|2) -> day ("Пнд"..) -> [Lesson]
    weeks: dict = field(default_factory=dict)
    pair_times: list = field(default_factory=lambda: list(DEFAULT_PAIR_TIMES))

    def day(self, week: int, day: str) -> list:
        return self.weeks.get(week, {}).get(day, [])

    def all_lessons(self):
        """Итератор по всем парам группы: (week, day, Lesson)."""
        for w, days in self.weeks.items():
            for d, lessons in days.items():
                for ls in lessons:
                    yield w, d, ls

    def subjects(self) -> list:
        """Уникальные предметы этой группы (отсортированы)."""
        return sorted({ls.subject for _, _, ls in self.all_lessons() if ls.subject})

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "href": self.href,
            "pair_times": list(self.pair_times),
            "weeks": {
                str(w): {d: [ls.to_dict() for ls in lessons]
                         for d, lessons in days.items()}
                for w, days in self.weeks.items()
            },
        }

    @staticmethod
    def from_dict(d: dict) -> "GroupSchedule":
        weeks = {}
        for w, days in (d.get("weeks") or {}).items():
            weeks[int(w)] = {
                day: [Lesson.from_dict(x) for x in lessons]
                for day, lessons in days.items()
            }
        return GroupSchedule(
            name=d.get("name", ""),
            href=d.get("href", ""),
            weeks=weeks,
            pair_times=d.get("pair_times") or list(DEFAULT_PAIR_TIMES),
        )


@dataclass
class Snapshot:
    """Цельный снимок расписания колледжа на момент парсинга.

    Кладётся целиком в локальный кэш (store.py). teacher_index — расписание
    преподавателей, полученное ИНВЕРСИЕЙ групповых: преподаватель -> week -> day ->
    [(group, Lesson)]. Так преподаватель видит свои пары, не дёргая отдельные
    страницы кафедр.
    """
    updated_at: str = ""
    groups: dict = field(default_factory=dict)            # name -> GroupSchedule
    subjects: list = field(default_factory=list)
    pair_times: list = field(default_factory=lambda: list(DEFAULT_PAIR_TIMES))
    #teacher -> week(int) -> day(str) -> [ {group, lesson} ]
    teacher_index: dict = field(default_factory=dict)

    def teachers(self) -> list:
        return sorted(self.teacher_index.keys())

    def group_names(self) -> list:
        return sorted(self.groups.keys())

    def to_dict(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "pair_times": list(self.pair_times),
            "subjects": list(self.subjects),
            "groups": {name: g.to_dict() for name, g in self.groups.items()},
            "teacher_index": {
                t: {str(w): {d: [{"group": e["group"], "lesson": e["lesson"].to_dict()}
                                 for e in entries]
                             for d, entries in days.items()}
                    for w, days in weeks.items()}
                for t, weeks in self.teacher_index.items()
            },
        }

    @staticmethod
    def from_dict(d: dict) -> "Snapshot":
        groups = {name: GroupSchedule.from_dict(g)
                  for name, g in (d.get("groups") or {}).items()}
        tindex = {}
        for t, weeks in (d.get("teacher_index") or {}).items():
            tindex[t] = {}
            for w, days in weeks.items():
                tindex[t][int(w)] = {
                    day: [{"group": e.get("group", ""),
                           "lesson": Lesson.from_dict(e.get("lesson", {}))}
                          for e in entries]
                    for day, entries in days.items()
                }
        return Snapshot(
            updated_at=d.get("updated_at", ""),
            groups=groups,
            subjects=list(d.get("subjects") or []),
            pair_times=d.get("pair_times") or list(DEFAULT_PAIR_TIMES),
            teacher_index=tindex,
        )
