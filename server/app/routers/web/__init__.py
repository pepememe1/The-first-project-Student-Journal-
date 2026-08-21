"""
routers/web — READ- и WRITE-представления для веб-версии (SPA). Всё СТРОГО по роли.

Зачем отдельно от /sync: pull отдаёт все строки всех таблиц (включая password_hash и
чужие оценки) — в браузер это выгружать нельзя. Здесь сервер отдаёт только то, что
роль вправе видеть, уже в готовом для UI виде. Средний балл считается через grading.py
(единый источник), поэтому цифры совпадают с десктопом.

Есть и ЗАПИСЬ (Phase B, модуль `write`): преподаватель ставит оценки, админ ведёт CRUD
студентов. Пишем в те же таблицы и в том же формате id, что и синк десктопа — правки
подхватываются десктопом обычным pull; метку LWW ставит сервер (инвариант §3).

━━ РАСКЛАДКА (3.6) ━━
Раньше всё это было ОДНИМ файлом на 4288 строк, который принял 62 коммита за полгода —
самый горячий файл репозитория и главный источник конфликтов при работе вдвоём. Теперь:

    _common.py     роутер, импорты, проверки доступа, общие утилиты
    student.py     кабинет студента
    teacher.py     кабинет преподавателя (чтение)
    terms.py       учебный период и перевод на следующий семестр
    curator.py     курируемые группы, ЗЕТ-отчёт, риск отчисления
    termgrades.py  итоговые оценки и ведомости
    admin_read.py  справочники администратора (чтение)
    siteinfo.py    инфо-панель сервера и сайта
    schedule.py    расписание портала, редактор правок, сверка накладок
    vector.py      «Вектор», голосовой ввод и озвучка
    write.py       ЗАПИСЬ: оценки, занятия, CRUD администратора
    datatransfer.py выгрузка/загрузка данных и резервные копии

⚠️ ПОРЯДОК ИМПОРТА НИЖЕ ЗНАЧИМ. Маршруты регистрируются в момент импорта модуля, а
FastAPI выбирает ПЕРВЫЙ подошедший — как было в едином файле, так и оставляем. Менять
порядок можно, только понимая, какие пути начнут перехватываться раньше.

⚠️ Публичные имена ре-экспортируются ниже: на них смотрят соседние роутеры
(`messenger`, `parent`), `schedule_conflicts` и тесты. Их пути импорта (`from .web
import ...`) от разреза НЕ изменились — в этом и был смысл делать пакет с тем же именем.
"""
from ._common import router                       # noqa: F401

#Порядок — тот же, в котором секции шли в исходном файле.
from . import student                             # noqa: F401,E402
from . import teacher                             # noqa: F401,E402
from . import terms                               # noqa: F401,E402
from . import curator                             # noqa: F401,E402
from . import termgrades                          # noqa: F401,E402
from . import admin_read                          # noqa: F401,E402
from . import siteinfo                            # noqa: F401,E402
from . import schedule                            # noqa: F401,E402
from . import vector                              # noqa: F401,E402
from . import write                                # noqa: F401,E402
from . import datatransfer                        # noqa: F401,E402
from . import courses                             # noqa: F401,E402

#Совместимость: имена, которые импортируют снаружи.
from ._common import (_resolve_term, _require, _ensure_current_term,  # noqa: F401,E402
                      _teacher_check_assignment, _curator_check,
                      _admin_or_curator_check, _file_response, _now_iso)
from .vector import (answer_vector_question, user_ui_locale,  # noqa: F401,E402
                     _NO_VOICE_INTENTS)
from .schedule import _apply_overrides, _group_schedule       # noqa: F401,E402
