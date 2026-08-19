"""
sync_engine.py — Слой-переходник offline-first синхронизации (вариант А).

Зачем: модели данных десктопа и сервера НЕ совпадают. Десктоп хранит студентов,
преподавателей и группы как JSON-списки/словари в kv_store, а бэкенд — как
отдельные строки (users/groups/subjects/...). Этот модуль переводит одно в другое
в обе стороны, чтобы прога продолжала хранить данные как раньше, а на сервер
уходил/приходил формат API.

Устройство:
  • «Чистые» функции перевода (subjects_to_rows, config_from_pull и т.п.) — без БД и без
    сети, легко тестируются round-trip'ом.
  • Функции _collect_* / _merge_* работают с локальной БД ПРЯМЫМ SQL — это ОСОЗНАННО, а
    не недосмотр: запись через data_store.set_* БУДИТ фоновый синк, и применение
    серверных данных зациклилось бы («синк → запись → синк»). Поэтому приём с сервера
    идёт мимо data_store, напрямую в таблицы, с меткой сервера (stamp=False по смыслу).
    Плата — слой знает схему SQLite; при смене схемы править и здесь, и в data_store.
  • Оркестрация — функции sync_once/reconcile поверх `SyncSession` (флаги самолечения,
    счётчик циклов, замок цикла). Раньше это были четыре модульных глобала, и рядом
    стояло обещание «синк крутится в ОДНОМ фоновом потоке, параллельных циклов нет» —
    неправда с тех пор, как `sync_runner.flush_now()` начал звать цикл из потока
    закрытия программы. Теперь состояние принадлежит сеансу и защищено его замком.

Сетевой обмен — через sync_client. Любая сетевая ошибка не критична: синк
откладывается, прога работает офлайн.

ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ (осознанные, не забытые):
  • УДАЛЕНИЕ ПРЕДМЕТА через синк НЕ РАБОТАЕТ. apply_remote сливает предметы объединением
    множеств, а rows_to_subjects отбрасывает надгробия — значит удалённый на сервере
    предмет останется на клиенте навсегда. Сделано так намеренно: предметы лежат в
    subjects.json (не в таблице), общий список редактируется с нескольких сторон, и
    «сервер стирает локальные» приводило бы к потере правок. Занятия/оценки/группы
    удаляются штатно, через надгробия. Понадобится удаление предметов — заводить им
    таблицу с deleted, а не менять слияние.
  • СОСТАВНЫЕ КЛЮЧИ через `|` (`{student_id}|{lesson_id}`) неоднозначны, если сама
    часть содержит `|`. На практике student_id — это `stud:{логин}`, а lesson_id
    генерируется программой, так что риск теоретический. Появятся вольные логины —
    экранировать разделитель или уходить на UUID.

Push тоже ДЕЛЬТА (раньше уезжал полный снимок базы каждый цикл — трафик рос вместе с
числом занятий/оценок). Граница — локальная метка `_push_watermark`; чтобы дельта не
теряла правки, действуют три страховки: нестрогое сравнение `>=`, лаг PUSH_SAFETY_LAG_S
на случай отхода часов назад и полный снимок раз в FULL_PUSH_EVERY циклов и на старте
сессии. Push идемпотентен, поэтому «отправить лишний раз» всегда дешевле, чем потерять.
"""
import threading
from datetime import datetime, timezone

import log

_log = log.get("sync")


def _now() -> str:
    #UTC + микросекунды (единый формат с сервером и data_store._now_iso) —
    #чтобы LWW-сравнение строк не зависело от часового пояса клиента.
    return datetime.now(timezone.utc).isoformat()


def _ts_key(ts: str):
    """Метка времени → сопоставимое значение. РАЗБИРАЕМ строку, а не сравниваем как текст.

    Голое строковое сравнение ISO-меток хрупко: `datetime.isoformat()` ВЫБРАСЫВАЕТ
    микросекунды, когда они нулевые («…T14:30:00+00:00» против «…T14:30:00.000001+00:00»),
    а суффикс «Z» лексикографически БОЛЬШЕ «+00:00» и «.». Стоит одной стороне сменить
    формат — и LWW начнёт молча терять более свежие правки. Разбор в datetime это
    исключает; нераспознанное — сравниваем как строку (безопасный откат).

    ⚠️ Первый элемент пары — ВИД метки (1 — разобранная, 0 — нет), и он тут не для
    красоты: без него кортежи сравнивались бы вторыми элементами разных типов
    (float против str) и падали бы на TypeError. Именно эта пара позволяет
    `_should_apply` сравнивать метки одним `>`, не разбирая случаи вручную."""
    s = (ts or "").strip()
    if not s:
        return (0, "")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:                       #наивную метку считаем UTC
            d = d.replace(tzinfo=timezone.utc)
        return (1, d.timestamp())
    except (ValueError, TypeError):
        return (0, s)


def _should_apply(inc_ts: str, cur_ts: str, inc_deleted: bool) -> bool:
    """LWW с tie-break: применяем, если входящая метка позже; при РАВНОЙ метке —
    применяем только удаление (надгробие не должно «воскресать» из-за устаревшего
    живого пуша с той же меткой).

    Сравниваем кортежи ЦЕЛИКОМ, одним `>`. Отдельной ветки «одна метка разобралась,
    другая нет» здесь не нужно: Python сравнивает кортежи поэлементно и на разных
    видах метки решает уже по первому элементу (1 > 0 — разобранная новее), до
    второго не доходя. Отсюда же требование к `_ts_key`: вид метки обязан оставаться
    ПЕРВЫМ элементом пары, иначе сравнение упрётся в float против str."""
    a, b = _ts_key(inc_ts), _ts_key(cur_ts)
    return a > b or (a == b and bool(inc_deleted))


#Пользователи (студенты/преподаватели) синхронизируются ПРЯМЫМ upsert'ом из таблицы users
#(без переводчика — план №2, Стадия 2): сбор в _collect_users(), приём в _merge_users().
#Конвертацию desktop↔server-формы делает data_store на границе UI (get/set_students и т.п.).
#Группы — так же (таблица groups): _collect_groups() / _merge_groups().


#🔥 ПЕРЕВОДЧИК ПРЕДМЕТОВ УДАЛЁН вместе с `subjects.py` (17.08.2026, решение Ярослава:
#«зависим чисто от портала ВСГУТУ»). Здесь были `subjects_to_rows`/`rows_to_subjects` —
#мост между локальным `subjects.json` и таблицей `subjects`.
#Почему ушёл целиком, а не «починили направление»: список предметов десктоп брал ПЕРВЫМ
#делом с портала (`schedule.store.subjects_all`), а `subjects.json` со встроенными 68
#названиями был лишь откатом — то есть вторым, устаревающим источником правды. Он же и
#воскрешал на сервере предметы, удалённые администратором на сайте: отправить надгробие
#`subjects_to_rows` не умела в принципе, она штамповала `deleted: False` каждому имени.
#Предметы для интерфейса программы приезжают обычным pull в `local_app.db` (зеркало, на
#котором работает SPA) — этот путь не тронут.


#Конфиг + админ
#admin_password_hash уезжает как пользователь role=admin; остальные ключи — в config.

#🔥 `config_to_rows` и `admin_user_from_config` УДАЛЕНЫ 17.08.2026 вместе с push'ем
#настроек и синтетической строки админа (подробности — в докстринге `collect_local`).
#Удалены, а не оставлены «на всякий случай», намеренно: это были готовые помощники ровно
#для того направления обмена, которое теперь запрещено, и следующий читатель, увидев их
#рядом с живым `config_from_pull`, скорее всего решил бы, что обратный путь просто забыли
#подключить. История — в git.


def config_from_pull(config_rows: list, users: list, admin_login: str = "admin") -> dict:
    """Собирает обратно словарь config: ключи из config + хеш админа из users."""
    cfg = {}
    for r in config_rows:
        if not r.get("deleted") and r.get("key"):
            cfg[r["key"]] = r.get("value")
    for u in users:
        if u.get("role") == "admin" and not u.get("deleted") and u.get("password_hash"):
            cfg["admin_password_hash"] = u["password_hash"]
            break
    return cfg


#Сбор локальных данных в формат API (push) и применение (pull)
#Локальное хранилище — через data_store/DBManager (offline-first не ломаем).

def _collect_lessons() -> list:
    from contextlib import closing
    from data.core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            #Шлём ВСЕ занятия, включая надгробия (deleted=1) — иначе удаление не доедет
            #до других ПК и занятие воскреснет на следующем pull.
            cur.execute("SELECT id,group_name,subject,type,number,topic,date,"
                        "retake_date,hour,COALESCE(updated_at,''),COALESCE(deleted,0),"
                        "COALESCE(year,''),COALESCE(semester,0) FROM lessons")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать занятия для синка: %s", e)
        _session.collect_failed = True
    out = []
    for r in rows:
        out.append({
            "id": r[0], "group_name": r[1], "subject": r[2], "type": r[3],
            "number": r[4], "topic": r[5], "date": r[6], "retake_date": r[7],
            "hour": r[8], "extra": {}, "updated_at": r[9] or _now(),
            "deleted": bool(r[10]),
            "year": r[11], "semester": r[12],   #учебный период — общий с сервером/вебом
        })
    return out


def _collect_grades() -> list:
    from contextlib import closing
    from data import core as _core
    from data.core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            #Шлём ВСЕ оценки, включая надгробия (deleted=1) — чтобы удаление оценки
            #распространилось, а не «воскресло» при следующем pull.
            cur.execute("SELECT student_f,student_n,lesson_id,grade,"
                        "COALESCE(updated_at,''),COALESCE(device,''),"
                        "COALESCE(deleted,0),COALESCE(student_id,'') FROM grades")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать оценки для синка: %s", e)
        _session.collect_failed = True
    out = []
    for f, n, lid, grade, uat, dev, deleted, sid in rows:
        out.append({
            #ЭТАП 3: ключ по неизменяемому student_id. Не опознан — уезжает СТАРЫЙ
            #ФИО-ключ (сервер нормализует его на приёме, см. sync._normalize_grade_key):
            #ростер препода ведётся отдельно, и такая оценка законна — терять её нельзя.
            "id": (_core.grade_id(sid, lid) if sid else f"{f}|{n}|{lid}"),
            "student_f": f, "student_n": n, "lesson_id": lid,
            "grade": grade, "device": dev, "updated_at": uat or _now(),
            "deleted": bool(deleted),
            #Этап 1 миграции: ключ пока ФИО, но неизменяемый id везём рядом. Сервер его
            #сохранит, и после бэкофилла привязку можно будет переключить, не потеряв
            #историю переименованных студентов.
            "student_id": sid,
        })
    return out


def _collect_users() -> list:
    """Пользователи (студенты/преподаватели) из таблицы users в СЕРВЕРНОЙ форме (со
    надгробиями) — прямой push, без переводчика. Расшифровку blob'а делает data_store.
    Админ добавляется отдельно (его хеш — в config)."""
    from data.data_store import users_for_sync
    return users_for_sync()


def _collect_groups() -> list:
    """Группы из таблицы в формате API (со надгробиями) — прямой upsert, без переводчика."""
    import json as _json
    from contextlib import closing
    from data.core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:   #закроется и при исключении
            cur = conn.cursor()
            cur.execute("SELECT id,name,COALESCE(subjects,'[]'),COALESCE(updated_at,''),"
                        "COALESCE(deleted,0),specialty_code,enrollment_year,category FROM groups")
            rows = cur.fetchall()
    except Exception as e:
        #НЕ глушим молча: при залоченной/битой БД пустой список уехал бы как «нет групп»,
        #и локальные группы просто перестали бы синхронизироваться — без следа в логах.
        _log.error("не удалось прочитать группы для синка: %s", e)
        _session.collect_failed = True
    out = []
    for gid, name, subj, uat, deleted, specialty_code, enrollment_year, category in rows:
        try:
            subjects = _json.loads(subj) if subj else []
        except Exception:
            subjects = []
        out.append({"id": gid or f"grp:{name}", "name": name, "subjects": subjects,
                    "updated_at": uat or _now(), "deleted": bool(deleted),
                    "specialty_code": specialty_code or "",
                    "enrollment_year": enrollment_year,
                    "category": category or ""})
    return out


def _collect_term_grades() -> list:
    from contextlib import closing
    from data.core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            #Шлём ВСЕ итоговые, включая надгробия (deleted=1) — иначе снятие оценки не
            #доедет до других ПК/сайта и она «воскреснет» на следующем pull.
            cur.execute("SELECT id,student_f,student_n,subject,COALESCE(year,''),"
                        "COALESCE(semester,0),COALESCE(grade,''),COALESCE(form,''),"
                        "COALESCE(updated_at,''),COALESCE(deleted,0),"
                        "COALESCE(student_id,'') FROM term_grades")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать итоговые оценки для синка: %s", e)
        _session.collect_failed = True
    out = []
    for r in rows:
        out.append({
            "id": r[0], "student_f": r[1], "student_n": r[2], "subject": r[3],
            "year": r[4], "semester": r[5], "grade": r[6], "form": r[7],
            "updated_at": r[8] or _now(), "deleted": bool(r[9]),
            "student_id": r[10],            #этап 1 миграции — см. _collect_grades
        })
    return out


def _filter_since(rows: list, since: str) -> list:
    """Оставляет строки, изменённые не раньше метки. Граница НЕ строгая (`>=`) — по той же
    причине, что и в дельта-pull (§3 внутренних заметок): push и запись могут попасть в один тик
    часов, и при строгом «>» такая правка выпала бы из дельты навсегда. Push идемпотентен,
    поэтому лишний повтор безвреден, а потеря — нет."""
    if not since:
        return rows
    key = _ts_key(since)
    return [r for r in rows if _ts_key(r.get("updated_at", "")) >= key]


def collect_local(since: str = "") -> dict:
    """Читает локальное состояние и переводит в формат API (для push).

    since != "" — собираем ДЕЛЬТУ: только строки с updated_at >= since. Предметы отдаём
    всегда: их локальные «метки» синтезируются на лету (`_now()`), реальной истории
    изменений у них нет, а объём — десятки строк, фильтровать нечего.

    🔥 CONFIG И СИНТЕТИЧЕСКАЯ СТРОКА АДМИНА БОЛЬШЕ НЕ УЕЗЖАЮТ (17.08.2026). Раньше
    уезжали — целиком, КАЖДЫЙ цикл, с меткой `_now()`. Выглядело безобидно («одна строка,
    терпимо»), а стоило двух подтверждённых потерь данных, потому что `POST /sync/push` на
    сервере решает «применять или нет» СРАВНЕНИЕМ СОДЕРЖИМОГО и на `updated_at` не смотрит
    вовсе: у кого содержимое иное, тот и прав. Значит любая правка, сделанная на САЙТЕ
    между двумя циклами синка, откатывалась устаревшей копией десктопа — молча и навсегда:
      • настройки (`ConfigKV`). Ровно этим объясняется «воскресший оверрайд термина»,
        который в проекте чистили руками ДВАЖДЫ (3.6.1 и 3.7.4) и оба раза не нашли, кто
        создаёт его заново: кнопку перевода курса из интерфейса убрали, а десктоп продолжал
        досылать свою копию. Локальный `config` пополняется ТОЛЬКО из pull
        (`config_from_pull`) и ключи из него никогда не удаляются — то есть однажды
        увиденный ключ десктоп возвращал на сервер вечно;
      • пароль администратора. `admin_updated_at` ставит `data_store.set_admin_password`,
        у которой НЕТ ВЫЗЫВАЮЩЕГО с удаления Qt-оболочки, — значит фолбэк на `_now()`
        срабатывал всегда, строка админа уезжала каждый цикл и возвращала на сервер ПРЕЖНИЙ
        хеш. Смена пароля админа на сайте отменялась за полминуты, а `password_set_at`
        оставался новым: карточка показывала «пароль выдан только что», работал старый.
    Почему выключение безопасно: локальный `config` на десктопе НЕ ПИШЕТ НИКТО, кроме
    приёма серверных данных (единственный писатель — `set_admin_password`, у неё нет
    вызывающего; это признаёт и шапка `data_store.py`). То есть в push он мог только
    откатывать чужое, но никогда ничего не привносил. Появится на десктопе настоящий
    редактор настроек — возвращать не «как было», а с честной локальной меткой изменения и
    сравнением её на сервере. Держат `server/tests/test_sync_config_clobber.py` и
    `tests/test_sync_does_not_clobber_server_config.py`.
    Приём с сервера (`apply_remote`) НЕ ТРОНУТ: методика оценок и настройки по-прежнему
    приезжают на ПК и нужны офлайн-расчёту."""

    def _safe(name: str, fn):
        """Позвать коллектор так, чтобы его сбой не уронил цикл — но и не солгал.

        🔥 Единая обёртка вместо семи одинаковых try/except внутри коллекторов. Так было
        не всегда, и цена разнобоя оказалась конкретной: шесть коллекторов ставили
        `collect_failed` сами, а седьмой (`_collect_users`) его не ставил ВООБЩЕ — при
        залоченной базе он отдавал пустой список, push проходил «успешно», и водяной знак
        уносил за собой неотправленные правки пользователей. Дефект нашёлся адверсариальным
        ревью, а не тестом: каждый коллектор по отдельности выглядел правильным.
        Теперь забыть флаг у НОВОГО коллектора нельзя — он ставится здесь, в одном месте.

        Пустой список при сбое — осознанно: одна нечитаемая таблица не должна лишать
        человека синхронизации целиком. Но флаг гарантирует, что метку дельты после этого
        не сдвинут, и тот же диапазон соберётся заново следующим циклом (push идемпотентен).
        """
        try:
            return fn()
        except Exception as e:                      # noqa: BLE001
            _session.collect_failed = True
            _log.error("таблица «%s» не прочиталась (%s) — метку дельты не двигаю, "
                       "эти правки уедут следующим циклом", name, e)
            return []

    #Пользователи — прямо из таблицы users (серверная форма, со надгробиями). Строку
    #админа сюда БОЛЬШЕ НЕ ДОБАВЛЯЕМ (см. докстринг): его хеш живёт в локальном config,
    #который заполняется только приёмом с сервера, — отправлять его обратно значит
    #отменять смену пароля, сделанную на сайте.
    users = _safe("users", _collect_users)
    return {
        "users": _filter_since(users, since),
        #🔥 `subjects` НЕ УЕЗЖАЮТ (17.08.2026) — по той же причине и с тем же механизмом,
        #что `config` выше. `subjects_to_rows` физически не умеет отправить надгробие: она
        #штампует `deleted: False` каждому имени из локального списка. А push применяет
        #правку по содержимому, значит удалённый на сайте предмет ОЖИВАЛ на сервере на
        #ближайшем цикле — и так бесконечно, потому что из `subjects.json` имя не уходит
        #никогда (приём делает ОБЪЕДИНЕНИЕ множеств, см. `apply_remote`). Свежая установка
        #вдобавок досылала на бой ВСТРОЕННЫЙ список по умолчанию.
        #Десктоп предметы не авторствует: локально `save_subjects` зовут только очистка
        #кэша и наполнение дефолтом, каталог ведут на сайте.
        "groups": _filter_since(_safe("groups", _collect_groups), since),
        "lessons": _filter_since(_safe("lessons", _collect_lessons), since),
        "grades": _filter_since(_safe("grades", _collect_grades), since),
        "term_grades": _filter_since(_safe("term_grades", _collect_term_grades), since),
        "schedule_overrides": _filter_since(
            _safe("schedule_overrides", _collect_schedule_overrides), since),
        "subject_hours": _filter_since(
            _safe("subject_hours", _collect_subject_hours), since),
    }


def apply_remote(changes: dict):
    """Применяет пришедшие с сервера изменения в локальное хранилище (LWW-слияние).
    Пишем с stamp=False — сохраняем серверные метки, чтобы синк не зациклился."""
    from data.data_store import get_store, _kv_set
    st = get_store()
    users = changes.get("users", []) or []

    #Пользователи — прямой LWW-upsert в таблицу users (студенты/преподаватели). Админ
    #(role=admin) в таблицу НЕ пишем — его хеш применяется в config ниже (config_from_pull).
    if users:
        _merge_users(users)

    #Группы — прямой LWW-upsert в таблицу groups (как lessons/term_grades), без переводчика.
    if changes.get("groups"):
        _merge_groups(changes["groups"])

    #Предметы в локальный файл БОЛЬШЕ НЕ ПИШЕМ (`subjects.json` и `subjects.py` удалены).
    #Их читал только этот же модуль, а интерфейсу программы предметы приезжают обычным
    #pull в `local_app.db` — зеркальную копию, на которой работает SPA (`local_mirror`
    #применяет ВСЕ таблицы SYNC_MODELS, включая `subjects`). То есть путь до экрана не
    #тронут: убран второй, параллельный склад того же списка.

    #Конфиг (ключи) + хеш админа
    if "config" in changes or users:
        new_cfg = config_from_pull(changes.get("config", []), users, st.get_admin_login())
        cfg = st._config()
        cfg.update(new_cfg)
        _kv_set("config", cfg, wake=False)   #серверные данные — синк не будим

    #Занятия и оценки
    if changes.get("lessons"):
        _merge_lessons(changes["lessons"])
    if changes.get("grades"):
        _merge_grades(changes["grades"])
    if changes.get("term_grades"):
        _merge_term_grades(changes["term_grades"])
    #Правки расписания (overlay) — общие веб↔десктоп, прямой LWW-upsert (как группы).
    if changes.get("schedule_overrides"):
        _merge_schedule_overrides(changes["schedule_overrides"])
    #Плановые часы предметов — задаёт админ, десктоп показывает «пройдено X из Y».
    if changes.get("subject_hours"):
        _merge_subject_hours(changes["subject_hours"])


def _merge_lessons(remote: list):
    from contextlib import closing
    from data.core import DBManager
    #closing гарантирует закрытие даже при исключении: раньше при ошибке
    #посреди слияния соединение утекало, и пул рано или поздно исчерпывался.
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        for l in remote:
            lid = l.get("id")
            if not lid:
                continue
            rdel = bool(l.get("deleted"))
            cur.execute("SELECT COALESCE(updated_at,'') FROM lessons WHERE id=?", (lid,))
            row = cur.fetchone()
            #LWW с tie-break: применяем, если входящая метка позже (или при равной —
            #если это удаление). Так удаление с сервера тоже применяется к локали.
            if not (row is None or _should_apply(l.get("updated_at", ""), row[0] or "", rdel)):
                continue
            #deleted переносим как есть: 1 — занятие становится надгробием (исчезнет из
            #журнала, фильтр deleted=0 в load_from_db), 0 — обычное активное занятие.
            cur.execute(
                "INSERT OR REPLACE INTO lessons "
                "(id,group_name,subject,type,number,topic,date,retake_date,hour,"
                "year,semester,updated_at,deleted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lid, l.get("group_name", ""), l.get("subject", ""), l.get("type", ""),
                 l.get("number", 0), l.get("topic", ""), l.get("date", ""),
                 l.get("retake_date", ""), l.get("hour", 0),
                 l.get("year", "") or "", int(l.get("semester", 0) or 0),
                 l.get("updated_at", ""), 1 if rdel else 0))
        conn.commit()


def _merge_users(remote: list):
    """Слияние пользователей (студенты/преподаватели) с сервера — прямой LWW с tie-break
    в таблицу users. payload шифруем в blob (Fernet+DPAPI) — хеши паролей и ПДн на диске
    защищены (152-ФЗ). role=admin пропускаем: его хеш применяется в config (не тут)."""
    import json as _json
    from data.core import DBManager
    from data.security import encrypt_value
    from contextlib import closing
    #closing гарантирует закрытие даже при исключении: раньше при ошибке
    #посреди слияния соединение утекало, и пул рано или поздно исчерпывался.
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, role TEXT, "
                    "updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0, blob TEXT DEFAULT '')")
        for u in remote:
            role = u.get("role")
            #§12: роль parent тоже должна доехать до локальной таблицы — иначе вход
            #родителя на десктопе всегда проваливался: сервер подтверждал пароль верным,
            #а lookup_session/get_parents (data_store.py) не находили строку локально.
            if role not in ("student", "teacher", "parent"):
                continue
            uid = u.get("id")
            if not uid:
                continue
            rdel = bool(u.get("deleted"))
            cur.execute("SELECT COALESCE(updated_at,'') FROM users WHERE id=?", (uid,))
            row = cur.fetchone()
            if not (row is None or _should_apply(u.get("updated_at", ""), row[0] or "", rdel)):
                continue
            cur.execute("INSERT OR REPLACE INTO users (id,role,updated_at,deleted,blob) "
                        "VALUES (?,?,?,?,?)",
                        (uid, role, u.get("updated_at", ""), 1 if rdel else 0,
                         encrypt_value(_json.dumps(u, ensure_ascii=False))))
        conn.commit()


_SOVR_COLS = ("id", "group_name", "week", "day", "pair_no", "action", "subject",
              "time", "room", "teacher", "kind")


def _ensure_sovr_table(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS schedule_overrides (id TEXT PRIMARY KEY, "
                "group_name TEXT, week INTEGER DEFAULT 1, day TEXT, pair_no INTEGER DEFAULT 0, "
                "action TEXT DEFAULT 'set', subject TEXT, time TEXT, room TEXT, teacher TEXT, "
                "kind TEXT, updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0)")


def _collect_schedule_overrides() -> list:
    """Правки расписания из локальной таблицы (со надгробиями) — прямой upsert в синк."""
    from contextlib import closing
    from data.core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            _ensure_sovr_table(cur)
            cur.execute("SELECT id,group_name,week,day,pair_no,action,subject,time,room,"
                        "teacher,kind,COALESCE(updated_at,''),COALESCE(deleted,0) "
                        "FROM schedule_overrides")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать правки расписания для синка: %s", e)
        _session.collect_failed = True
    out = []
    for r in rows:
        out.append({"id": r[0], "group_name": r[1], "week": r[2], "day": r[3], "pair_no": r[4],
                    "action": r[5], "subject": r[6], "time": r[7], "room": r[8], "teacher": r[9],
                    #Пустую метку подменяем на now, как во всех остальных коллекторах.
                    #Иначе правка без метки считалась бы САМОЙ СТАРОЙ и её затирала бы
                    #любая серверная версия (LWW сравнивает именно updated_at).
                    "kind": r[10], "updated_at": r[11] or _now(), "deleted": bool(r[12])})
    return out


def _merge_schedule_overrides(remote: list):
    """Слияние правок расписания с сервера — прямой LWW-upsert (как группы). Пишем прямо
    в таблицу, синк не будим (серверные данные, а не UI-правка)."""
    from contextlib import closing
    from data.core import DBManager
    #closing гарантирует закрытие даже при исключении: раньше при ошибке
    #посреди слияния соединение утекало, и пул рано или поздно исчерпывался.
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        _ensure_sovr_table(cur)
        for o in remote:
            oid = o.get("id")
            if not oid:
                continue
            rdel = bool(o.get("deleted"))
            cur.execute("SELECT COALESCE(updated_at,'') FROM schedule_overrides WHERE id=?", (oid,))
            row = cur.fetchone()
            if not (row is None or _should_apply(o.get("updated_at", ""), row[0] or "", rdel)):
                continue
            cur.execute(
                "INSERT OR REPLACE INTO schedule_overrides "
                "(id,group_name,week,day,pair_no,action,subject,time,room,teacher,kind,updated_at,deleted) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (oid, o.get("group_name", ""), int(o.get("week") or 1), o.get("day", ""),
                 int(o.get("pair_no") or 0), o.get("action", "set"), o.get("subject", ""),
                 o.get("time", ""), o.get("room", ""), o.get("teacher", ""), o.get("kind", ""),
                 o.get("updated_at", ""), 1 if rdel else 0))
        conn.commit()


def _ensure_hours_table(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS subject_hours (id TEXT PRIMARY KEY, "
                "group_name TEXT, subject TEXT, year TEXT, semester INTEGER DEFAULT 0, "
                "hours_total INTEGER DEFAULT 0, updated_at TEXT DEFAULT '', "
                "deleted INTEGER DEFAULT 0, teacher_id TEXT DEFAULT '', zet REAL)")
    try:
        cur.execute("ALTER TABLE subject_hours ADD COLUMN teacher_id TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE subject_hours ADD COLUMN zet REAL")
    except Exception:
        pass


def _collect_subject_hours() -> list:
    """Плановые часы из локальной таблицы — прямой upsert в синк (как правки расписания).

    Десктоп их обычно только ЧИТАЕТ (задаёт админ на сайте), но отдаём в push всё равно:
    иначе локально заведённая строка навсегда осталась бы на одной машине."""
    from contextlib import closing
    from data.core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            _ensure_hours_table(cur)
            cur.execute("SELECT id,group_name,subject,year,COALESCE(semester,0),"
                        "COALESCE(hours_total,0),COALESCE(updated_at,''),COALESCE(deleted,0),"
                        "COALESCE(teacher_id,''),zet FROM subject_hours")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать учебные часы для синка: %s", e)
        _session.collect_failed = True
    out = []
    for r in rows:
        out.append({"id": r[0], "group_name": r[1], "subject": r[2], "year": r[3],
                    "semester": int(r[4] or 0), "hours_total": int(r[5] or 0),
                    #Пустую метку подменяем на now — как во всех остальных коллекторах
                    #(иначе строка считалась бы самой старой и её затирало бы что угодно).
                    "updated_at": r[6] or _now(), "deleted": bool(r[7]), "teacher_id": r[8],
                    "zet": r[9]})
    return out


def _merge_subject_hours(remote: list):
    """Слияние учебных часов с сервера — прямой LWW-upsert (как правки расписания)."""
    from contextlib import closing
    from data.core import DBManager
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        _ensure_hours_table(cur)
        for h in remote:
            hid = h.get("id")
            if not hid:
                continue
            rdel = bool(h.get("deleted"))
            cur.execute("SELECT COALESCE(updated_at,'') FROM subject_hours WHERE id=?", (hid,))
            row = cur.fetchone()
            if not (row is None or _should_apply(h.get("updated_at", ""), row[0] or "", rdel)):
                continue
            cur.execute(
                "INSERT OR REPLACE INTO subject_hours "
                "(id,group_name,subject,year,semester,hours_total,updated_at,deleted,teacher_id,zet) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (hid, h.get("group_name", ""), h.get("subject", ""), h.get("year", ""),
                 int(h.get("semester") or 0), int(h.get("hours_total") or 0),
                 h.get("updated_at", ""), 1 if rdel else 0, h.get("teacher_id", ""),
                 h.get("zet")))
        conn.commit()


def _merge_groups(remote: list):
    """Слияние групп с сервера — прямой LWW с tie-break в таблицу groups (как занятия).
    Пишем напрямую в таблицу (не через data_store.set_groups) — так синк НЕ будит сам
    себя (это применение серверных данных, а не UI-правка)."""
    import json as _json
    from contextlib import closing
    from data.core import DBManager
    #closing гарантирует закрытие даже при исключении: раньше при ошибке
    #посреди слияния соединение утекало, и пул рано или поздно исчерпывался.
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS groups (id TEXT PRIMARY KEY, name TEXT, "
                    "subjects TEXT DEFAULT '[]', updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0, "
                    "specialty_code TEXT, enrollment_year INTEGER, category TEXT)")
        for g in remote:
            name = g.get("name", "")
            gid = g.get("id") or (f"grp:{name}" if name else "")
            if not gid:
                continue
            rdel = bool(g.get("deleted"))
            cur.execute("SELECT COALESCE(updated_at,'') FROM groups WHERE id=?", (gid,))
            row = cur.fetchone()
            if not (row is None or _should_apply(g.get("updated_at", ""), row[0] or "", rdel)):
                continue
            cur.execute("INSERT OR REPLACE INTO groups "
                        "(id,name,subjects,updated_at,deleted,specialty_code,enrollment_year,category) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (gid, name, _json.dumps(g.get("subjects") or [], ensure_ascii=False),
                         g.get("updated_at", ""), 1 if rdel else 0,
                         g.get("specialty_code") or "", g.get("enrollment_year"),
                         g.get("category") or ""))
        conn.commit()


def _merge_grades(remote: list):
    """Слияние оценок с сервера. Оценки — чувствительные данные, поэтому здесь НЕ
    слепой LWW, а детектор конфликтов: если серверное значение оценки расходится
    с локальным и локальное не новее — расхождение пишем в sync_conflicts и НЕ
    затираем работу преподавателя. Если значения совпали или локальное новее —
    конфликта нет.

    🔥 ЧЕСТНО ПРО ВТОРУЮ ПОЛОВИНУ. Здесь стояло «он решит вручную через conflict_dialog».
    Такого модуля НЕТ: диалог жил в Qt-оболочке и удалён вместе с ней, а `DBManager.
    list_conflicts`/`resolve_conflict` с тех пор не зовёт НИКТО. То есть расхождение
    честно фиксировалось — и оставалось невидимым навсегда: в журнале преподавателя одна
    оценка, на сервере другая, и никто об этом не узнаёт. Это тот же класс, что «обещание
    без вызывающего» у `reconcile`.
    Пока экрана нет, конфликт хотя бы ЗВУЧИТ: WARNING в лог + счётчик в
    `sync_runner.status()['conflicts']` (ровно так же поступили с `rejected`). Настоящий
    разбор в интерфейсе — отдельная работа, и до неё цифра в статусе не должна быть нулём
    молча.

    🔥 И ВТОРАЯ ПОЛОВИНА ПРАВДЫ, которой здесь не было (найдено адверсариальным разбором
    19.08.2026). «Не затираем работу преподавателя» верно только для ЭТОГО ПК и только
    до ближайшего ПОЛНОГО снимка. Дальше: полный push уходит на старте сессии и раз в
    `FULL_PUSH_EVERY` = 20 циклов, он не фильтруется по метке (`_filter_since` с пустым
    `since` отдаёт ВСЕ строки), а `POST /sync/push` решает «применять или нет»
    СРАВНЕНИЕМ СОДЕРЖИМОГО и на `updated_at` не смотрит вовсе (инвариант в CLAUDE.md,
    `server/app/routers/sync.py`: `compare_cols = cols - {pk, "updated_at"}`). Значит наш
    локальный балл ЗАТРЁТ серверный — молча и без разрешения конфликта, а строка в
    `sync_conflicts` останется `resolved=0` навсегда и счётчик будет показывать
    расхождение, которого в данных уже нет.
    То есть исход конфликта сегодня — «побеждает тот, кто раньше отправит полный
    снимок», а не «две правды ждут человека». Это осознанно НЕ чинится здесь: не слать
    конфликтные строки вовсе значит навсегда запереть правку преподавателя на его ПК
    (экрана разрешения нет), и это хуже. Настоящее лекарство — `prev_updated_at` вместо
    тихого LWW (шаг 4 плана синка) плюс экран разбора.

    Метки сравниваем через _ts_key, а НЕ строками. Раньше здесь стояло голое `lat > rat`,
    и это противоречило всему остальному модулю: `isoformat()` выбрасывает нулевые
    микросекунды, а «Z» лексикографически больше «+00:00». Стоило серверу и клиенту
    разойтись в формате — и оценка либо молча затиралась, либо бесконечно порождала
    конфликт. Ровно то, от чего _ts_key и заводился."""
    from contextlib import closing
    from data.core import DBManager
    #closing гарантирует закрытие даже при исключении: раньше при ошибке
    #посреди слияния соединение утекало, и пул рано или поздно исчерпывался.
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        #Таблица конфликтов нужна гарантированно (на случай, если init не отработал).
        cur.execute("CREATE TABLE IF NOT EXISTS sync_conflicts ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "student_f TEXT, student_n TEXT, lesson_id TEXT,"
                    "local_grade TEXT, remote_grade TEXT, remote_device TEXT,"
                    "remote_at TEXT, detected_at TEXT, resolved INTEGER DEFAULT 0)")
        now_iso = _now()
        for g in remote:
            f, n, lid = g.get("student_f"), g.get("student_n"), g.get("lesson_id")
            rgrade = g.get("grade", "")
            rat = g.get("updated_at", "")
            rdev = g.get("device", "")
            rdel = bool(g.get("deleted"))
            cur.execute("SELECT grade, COALESCE(updated_at,''), COALESCE(deleted,0) FROM grades "
                        "WHERE student_f=? AND student_n=? AND lesson_id=?", (f, n, lid))
            local = cur.fetchone()

            #Удаление с сервера (надгробие). Применяем по LWW (новее побеждает); диалог
            #конфликтов для удалений не заводим — это не «два разных балла», а явное
            #удаление. Если локальная правка новее — оставляем её (уедет на сервер).
            if rdel:
                if local is None:
                    continue                       #нечего удалять
                lgrade, lat, ldel = local
                if ldel:
                    continue                       #уже удалено
                #Решение о применении — ТОЛЬКО через общее правило `_should_apply`
                #(при равной метке удаление побеждает). Здесь раньше стояло своё
                #сравнение; поведение совпадало, но именно так расходятся копии правила.
                if not _should_apply(rat, lat, True):
                    continue                       #локальная правка новее — оставляем
                cur.execute("UPDATE grades SET deleted=1, updated_at=?, device=?, "
                            "student_id=COALESCE(NULLIF(?,''),student_id) "
                            "WHERE student_f=? AND student_n=? AND lesson_id=?",
                            (rat, rdev, g.get("student_id", "") or "", f, n, lid))
                continue

            #Активная оценка с сервера.
            if local is None:
                #Локально такой оценки нет — просто принимаем серверную.
                cur.execute(
                    "INSERT OR REPLACE INTO grades "
                    "(student_f,student_n,lesson_id,grade,updated_at,device,deleted,"
                    "student_id) VALUES (?,?,?,?,?,?,0,?)",
                    (f, n, lid, rgrade, rat, rdev, g.get("student_id", "") or ""))
                continue
            lgrade, lat, ldel = local
            if ldel:
                #Локально оценка была удалена, а с сервера пришла активная (её
                #восстановили на другом ПК). Применяем, только если серверная СТРОГО
                #новее надгробия — при равной метке побеждает удаление (`_should_apply`).
                #🔥 Здесь стояло `not (_ts_key(lat) > _ts_key(rat))`, то есть на РАВНЫХ
                #метках удалённая оценка воскресала — прямо против общего правила.
                #Равенство тут не экзотика: метку обеим записям ставит сервер, а часы
                #Windows дискретны до ~16 мс (по этой же причине дельта-pull фильтрует
                #`>=`, а не `>`). Двое преподавателей в один тик — и снятая оценка
                #возвращалась в журнал. Держит
                #`tests/test_sync_reliability.py::test_equal_timestamp_does_not_resurrect_deleted_grade`.
                if _should_apply(rat, lat, False):
                    cur.execute(
                        "INSERT OR REPLACE INTO grades "
                        "(student_f,student_n,lesson_id,grade,updated_at,device,deleted,"
                        "student_id) VALUES (?,?,?,?,?,?,0,?)",
                        (f, n, lid, rgrade, rat, rdev, g.get("student_id", "") or ""))
                continue
            if (lgrade or "") == (rgrade or ""):
                continue   #значения совпали — менять нечего
            if _ts_key(lat) > _ts_key(rat):
                continue   #локальная правка новее — оставляем, она уедет на сервер
            #Значения разошлись, и серверное не старше локального → НАСТОЯЩИЙ конфликт.
            #Локальное значение НЕ трогаем; фиксируем расхождение для ручного решения.
            cur.execute("SELECT 1 FROM sync_conflicts WHERE student_f=? AND student_n=? "
                        "AND lesson_id=? AND resolved=0", (f, n, lid))
            if cur.fetchone() is None:   #не плодим дубли по одной и той же оценке
                cur.execute(
                    "INSERT INTO sync_conflicts "
                    "(student_f,student_n,lesson_id,local_grade,remote_grade,"
                    "remote_device,remote_at,detected_at,resolved) "
                    "VALUES (?,?,?,?,?,?,?,?,0)",
                    (f, n, lid, lgrade, rgrade, rdev, rat, now_iso))
                #Без этой строки расхождение было бы полностью беззвучным: строку в
                #таблице не читает ни один экран (см. докстринг функции). ФИО в лог не
                #пишем — там ПДн; занятия и значений оценок достаточно, чтобы найти место.
                _log.warning(
                    f"[sync] конфликт оценки: занятие {lid}, у нас {lgrade!r}, "
                    f"на сервере {rgrade!r} (с устройства {rdev or '?'}). "
                    f"Локальное значение сохранено, расхождение НЕ разрешено.")
        conn.commit()


def _merge_term_grades(remote: list):
    """Слияние итоговых оценок (аттестации) с сервера — простой LWW с tie-break
    (как занятия). Диалог конфликтов тут не нужен: это одна итоговая оценка за
    семестр, а не «два разных балла за занятие» — побеждает более поздняя правка."""
    from contextlib import closing
    from data.core import DBManager
    #closing гарантирует закрытие даже при исключении: раньше при ошибке
    #посреди слияния соединение утекало, и пул рано или поздно исчерпывался.
    with closing(DBManager.get_conn()) as conn:
        cur = conn.cursor()
        for g in remote:
            gid = g.get("id")
            if not gid:
                continue
            rdel = bool(g.get("deleted"))
            cur.execute("SELECT COALESCE(updated_at,'') FROM term_grades WHERE id=?", (gid,))
            row = cur.fetchone()
            if not (row is None or _should_apply(g.get("updated_at", ""), row[0] or "", rdel)):
                continue
            cur.execute(
                "INSERT OR REPLACE INTO term_grades "
                "(id,student_f,student_n,subject,year,semester,grade,form,updated_at,deleted,"
                "student_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (gid, g.get("student_f", ""), g.get("student_n", ""), g.get("subject", ""),
                 g.get("year", ""), int(g.get("semester", 0) or 0), g.get("grade", ""),
                 g.get("form", ""), g.get("updated_at", ""), 1 if rdel else 0,
                 g.get("student_id", "") or ""))
        conn.commit()


#Страховка от «дырки» в дельта-push: локальные часы могут отойти назад (синхронизация
#времени, переезд через часовой пояс, виртуалка после сна). Тогда правка получила бы
#метку РАНЬШЕ watermark и не попала бы в дельту. Поэтому метку сдвигаем назад на лаг —
#последние две минуты правок уезжают повторно (push идемпотентен, это дёшево).
PUSH_SAFETY_LAG_S = 120

#И грубый предохранитель на всё остальное: раз в N циклов шлём полный снимок. Даже если
#какая-то правка мимо всех расчётов выпала из дельты, она уедет максимум через N циклов,
#а не потеряется навсегда. Дешевле, чем гарантировать безошибочность меток.
FULL_PUSH_EVERY = 20

#Максимум строк в ОДНОМ запросе push. Приём взят у RxDB (`batchSize`), см.
#docs/SYNC-RESEARCH-2026.md.
#
#🔥 Зачем. Раньше push уезжал ОДНИМ телом любого размера, и это давало отказ, который не
#лечится сам: первый полный снимок на базе за учебный год — это тысячи занятий и оценок,
#на школьном канале он не укладывается в read-таймаут (45 c), цикл считается неудачным,
#водяной знак НЕ двигается — и следующий цикл собирает РОВНО ТОТ ЖЕ объём и падает так же.
#Самолечения нет по построению: оно упирается в размер, а размер не меняется. Колледж с
#накопленной базой просто никогда бы не синхронизировался, причём в логе это выглядело бы
#как обычный обрыв связи.
#
#500 строк — не результат замера на бою (его не было), а осознанно скромная величина:
#тело такой пачки — сотни килобайт, что проходит по любому каналу с запасом. Ошибиться в
#меньшую сторону дёшево (лишние HTTP-запросы), в большую — значит вернуть исходный отказ.
PUSH_BATCH_ROWS = 500


class SyncSession:
    """Состояние ОДНОГО сеанса синхронизации: флаги самолечения, счётчик циклов, замок.

    Раньше всё это лежало модульными глобалами. Их было ровно четыре, и цена казалась
    небольшой — но она копилась в двух местах сразу:
      • тесты правили внутренности модуля напрямую (`sync_engine._push_cycles = 0`), и
        забытый сброс протекал в СОСЕДНИЙ тест, где выглядел как случайный «полный push»;
      • второй сеанс (два сервера, тест рядом с рабочим циклом) молча делил бы флаги с
        первым — то есть один гасил бы самолечение другого.
    Здесь состояние принадлежит экземпляру, а модульные функции ниже остались как были:
    ни один существующий вызывающий не тронут.
    """

    def __init__(self) -> None:
        #Первый синк сеанса делаем ПОЛНЫМ (since=""), даже если метка уже есть: так
        #лечится возможный дрейф — редкая потеря пограничной записи из-за гонки
        #«коммит против взятия метки». Дальше в течение сеанса тянем только дельту.
        self.full_pull_done = False
        #То же для PUSH. Пока программа была закрыта, часы могли сдвинуться, а правки —
        #прийти мимо синка (восстановление из бэкапа, ручной импорт).
        self.full_push_done = False
        self.push_cycles = 0
        #Что сервер ОТКЛОНИЛ в последнем push ({} — всё принято).
        self.last_rejected: dict[str, int] = {}
        #🔥 Хоть один коллектор не смог прочитать свою таблицу в этом цикле.
        #Зачем отдельный флаг. Коллекторы при сбое чтения возвращают ПУСТОЙ список (это
        #осознанно: одна залоченная таблица не должна ронять весь цикл и оставлять
        #человека без синхронизации вообще). Но пустой список неотличим от «изменений
        #нет» — push проходит успешно, и водяной знак уезжает вперёд, унося за собой
        #правки, которых сервер так и не увидел. Сервер их не удалит (удаление у нас
        #только по надгробиям), но расхождение будет жить до ближайшего полного снимка,
        #то есть до 20 циклов. Поэтому: читать не смогли — метку НЕ двигаем.
        self.collect_failed = False
        #Один цикл за раз.
        #🔥 Замка раньше не было, а докстринг модуля утверждал «синк крутится в ОДНОМ
        #потоке, параллельных циклов нет» — это перестало быть правдой:
        #`sync_runner.flush_now()` (до-отправка перед закрытием программы) зовёт цикл из
        #ДРУГОГО потока, пока фоновый `_loop` может быть в середине своего. Два
        #следствия, оба реальные:
        #  • `requests.Session` внутри SyncClient НЕ потокобезопасна — общий пул
        #    соединений портится при одновременном использовании;
        #  • водяной знак push двигали бы оба потока вперемешку, и правка, собранная
        #    одним, но не отправленная им, могла оказаться «за» меткой, выставленной
        #    другим, — то есть не уехать НИКОГДА (дельта её больше не увидит).
        #Замок НЕ реентерабельный намеренно: цикл не зовёт сам себя, а RLock скрыл бы
        #случайную рекурсию вместо того, чтобы показать её сразу.
        self.lock = threading.Lock()

    def reset(self) -> None:
        """Вернуть сеанс в исходное состояние (следующий цикл будет полным).

        Существует ради тестов: раньше каждый из них правил внутренности модуля руками,
        и забытое поле протекало в соседний тест."""
        self.full_pull_done = False
        self.full_push_done = False
        self.push_cycles = 0
        self.last_rejected = {}


#Сеанс по умолчанию — один на процесс (десктоп синхронизируется с одним сервером).
_session = SyncSession()


def last_rejected() -> dict:
    """Записи, отвергнутые сервером в последнем push ({} — всё принято).

    Нужен, чтобы расхождение «локально есть, на сервере нет» было ВИДНО, а не жило
    молча: см. разбор в `_sync_once_locked`."""
    return dict(_session.last_rejected)


def reset_session_state() -> None:
    """Сбросить состояние сеанса по умолчанию (для тестов и после смены сервера)."""
    _session.reset()


def force_full_push():
    """Следующий push будет ПОЛНЫМ снимком (не дельтой)."""
    _session.full_push_done = False


def force_full_pull():
    """Сбрасывает флаг «полный pull сеанса уже сделан», чтобы СЛЕДУЮЩИЙ sync_once
    тянул всё с сервера (since=""), а не дельту. Нужно после reset_synced_local_data:
    кэш стёрт, и его надо наполнить заново полным снимком сервера."""
    _session.full_pull_done = False


def reconcile(client) -> bool:
    """Реконсиляция «сервер = истина»: стереть локальный кэш данных и наполнить его
    заново ПОЛНЫМ снимком сервера. После этого локальные данные точно соответствуют
    серверу — «осиротевшие» локальные записи (которых на сервере нет) исчезают.

    ВАЖНО: вызывать только когда сервер ДОСТУПЕН и токен валиден (проверять заранее),
    иначе после очистки кэша полный pull не пройдёт и останется пустая база.

    СНАЧАЛА отправляем локальные изменения, и лишь потом стираем кэш. Иначе офлайн-
    правки, накопленные на клиентском ПК (например, оценки преподавателя, выставленные
    без сети и ещё не ушедшие на сервер), были бы уничтожены reset_synced_local_data()
    ДО отправки — безвозвратная потеря. Push идемпотентен: сервер применит только реально
    изменённое, а после полного pull эти же правки вернутся в кэш уже с серверной меткой.
    """
    from data.data_store import reset_synced_local_data
    #Всё под ОДНИМ замком: между «спасли правки» и «стёрли кэш» не должен влезть фоновый
    #цикл — он собрал бы дельту из данных, которые вот-вот исчезнут, и сдвинул бы за ними
    #водяной знак. Внутри зовём `_sync_once_locked`, а не `sync_once`: замок не
    #реентерабельный, и повторный захват был бы взаимной блокировкой.
    with _session.lock:
        #Спасаем офлайн-правки: пуш перед очисткой. Упал — кэш НЕ трогаем: он ещё цел,
        #вызывающий уйдёт в офлайн-ветку, данные важнее «чистоты».
        try:
            #Порциями: это ПОЛНЫЙ снимок, самый крупный push за всю жизнь программы, и
            #именно он вероятнее всего не влезал в таймаут. А цена его провала здесь
            #максимальная — следом идёт очистка кэша.
            _push_all(client, collect_local())
        except Exception as e:
            _log.warning("пуш офлайн-правок перед сбросом кэша не удался: %s", e)
            raise
        reset_synced_local_data()
        force_full_pull()
        force_full_push()   #кэш стёрт — «уже отправленному» верить нельзя, шлём полный снимок
        return _sync_once_locked(client)


def _iter_push_batches(changes: dict, batch_rows: int = PUSH_BATCH_ROWS):
    """Режет снимок на пачки не больше `batch_rows` строк, СОХРАНЯЯ порядок таблиц.

    ⚠️ Порядок важен и потому зафиксирован: `collect_local` отдаёт таблицы в порядке
    users → … → lessons → grades → …, и при нарезке он сохраняется, то есть занятие
    уезжает РАНЬШЕ оценок, которые на него ссылаются. Внешних ключей на сервере нет, и
    строго говоря порядок не обязателен — но обратный (оценки без занятий) выглядел бы в
    базе как мусор в те секунды, пока идут остальные пачки, а на этом состоянии мог бы
    отработать пуш-хук или отчёт. Меняешь порядок в `collect_local` — помни про это.

    Пустые таблицы в пачку не кладём: у нас удаление ТОЛЬКО по надгробиям, поэтому
    отсутствие ключа сервер не трактует как «удалить всё» (`test_push_is_idempotent`).
    """
    batch: dict = {}
    n = 0
    for name, rows in changes.items():
        rows = rows if isinstance(rows, list) else []
        i = 0
        while True:
            chunk = rows[i:i + (batch_rows - n)]
            if chunk:
                batch[name] = chunk
                n += len(chunk)
                i += len(chunk)
            if n >= batch_rows:
                yield batch
                batch, n = {}, 0
            if i >= len(rows):
                break
    if batch:
        yield batch


def _push_all(client, changes: dict) -> dict:
    """Отправить снимок, при необходимости — НЕСКОЛЬКИМИ запросами. Возвращает сводный
    ответ вида {'applied': {...}, 'rejected': {...}}.

    Помещается в одну пачку (обычный случай — десятки строк) — шлём ровно один запрос,
    как раньше: ни лишнего кода в горячем пути, ни изменения поведения.

    Обрыв на середине НЕ откатывает уже применённые пачки, и это правильно: push
    идемпотентен (upsert по ключу), а водяной знак не сдвинется, пока не пройдёт ВЕСЬ
    цикл, — значит следующий раз соберётся тот же диапазон и доедет остаток. Обратное
    (пытаться откатить полупринятое) потребовало бы транзакции через несколько HTTP-
    запросов, чего у нас нет и не будет.
    """
    batches = list(_iter_push_batches(changes))
    if len(batches) <= 1:
        return client.push(batches[0] if batches else changes) or {}

    total = sum(len(v) for v in changes.values() if isinstance(v, list))
    _log.info("push порциями: %d строк → %d запросов по %d",
              total, len(batches), PUSH_BATCH_ROWS)
    out: dict = {"applied": {}, "rejected": {}}
    for idx, part in enumerate(batches, 1):
        res = client.push(part) or {}
        for key in ("applied", "rejected"):
            for table, cnt in (res.get(key) or {}).items():
                out[key][table] = out[key].get(table, 0) + int(cnt or 0)
        _log.debug("push порция %d/%d принята", idx, len(batches))
    return out


def sync_once(client, wait: float | None = None) -> bool:
    """Один цикл синхронизации: отправить локальные изменения, забрать серверные.
    Возвращает True при успехе. Бросаемые сетевые ошибки ловит вызывающий код.

    ⚠️ Цикл ЦЕЛИКОМ под замком сеанса (см. `SyncSession.lock`): два одновременных цикла
    портили бы и HTTP-сессию клиента, и водяной знак дельты.

    `wait` — сколько секунд ждать замок (None — сколько угодно, для фонового цикла).
    Закрытие программы передаёт конечное значение: висеть на чужом push до 45 c при
    выходе нельзя, а правки всё равно уедут — тем самым циклом, который сейчас идёт."""
    if not _session.lock.acquire(timeout=wait if wait is not None else -1):
        #Замок занят — цикл уже идёт в другом потоке, и наши правки он соберёт сам
        #(дельта берётся по водяному знаку, а не по «чьи это правки»). Для выхода из
        #программы это правильный ответ: ждать чужой push до 45 c нельзя.
        _log.info("цикл синхронизации уже идёт — пропускаю параллельный запуск")
        return False
    try:
        return _sync_once_locked(client)
    finally:
        _session.lock.release()


def _sync_once_locked(client) -> bool:
    from datetime import timedelta

    from data.data_store import (get_push_watermark, get_sync_watermark,
                            set_push_watermark, set_sync_watermark)

    #1. Отправляем ДЕЛЬТУ локальных правок (роль ограничивает на сервере). Раньше уезжал
    #полный снимок базы каждый цикл: сервер применял только изменившееся, но трафик рос
    #вместе с базой. Полный снимок оставляем для первого цикла сессии и раз в
    #FULL_PUSH_EVERY циклов — как самоизлечение.
    #Метку берём ДО сбора: правка, сделанная во время push, попадёт в СЛЕДУЮЩУЮ дельту,
    #а не провалится между сбором и сохранением метки.
    mark = (datetime.now(timezone.utc) - timedelta(seconds=PUSH_SAFETY_LAG_S)).isoformat()

    #🔥 ЧАСЫ УШЛИ НАЗАД — дельте верить нельзя, шлём полный снимок.
    #PUSH_SAFETY_LAG_S закрывает регрессию только на ДВЕ МИНУТЫ, а реальные бывают куда
    #крупнее: ноутбук проснулся с отставшими часами, сработала синхронизация времени,
    #человек переставил дату руками. Правка, сделанная в «откатившийся» час, получает
    #метку РАНЬШЕ водяного знака и в дельту не попадает — то есть не уезжает до
    #ближайшего полного снимка (до FULL_PUSH_EVERY циклов), а выглядит это как обычная
    #успешная синхронизация. Приём подсмотрен у ElectricSQL, где граница дельты — позиция
    #в журнале, а не время: часов в протоколе нет вовсе. Полный курсор у нас впереди
    #(docs/SYNC-RESEARCH-2026.md, шаг 5), но САМ КЛАСС отказа закрывается здесь и сейчас:
    #граница уехала назад — не хитрим, отправляем всё.
    prev_mark = get_push_watermark()
    clock_back = bool(prev_mark) and _ts_key(mark) < _ts_key(prev_mark)
    if clock_back:
        _log.warning("часы ушли назад (граница дельты %s раньше прошлой %s) — "
                     "отправляю полный снимок, чтобы правки этого промежутка не потерялись",
                     mark, prev_mark)

    full_push = ((not _session.full_push_done)
                 or (_session.push_cycles % FULL_PUSH_EVERY == 0)
                 or clock_back)
    _session.collect_failed = False          #флаг относится к ЭТОМУ циклу, не к прошлому
    res = _push_all(client, collect_local("" if full_push else prev_mark))
    #Метку двигаем только после УСПЕШНОГО push: упало — правки останутся в дельте.
    #И только если СОБРАТЬ данные тоже удалось: пустой список из-за залоченной таблицы
    #выглядит как «изменений нет», и сдвиг метки унёс бы за собой неотправленные правки
    #(см. `SyncSession.collect_failed`). Оставляем метку на месте — следующий цикл
    #соберёт тот же диапазон заново, push идемпотентен.
    if _session.collect_failed:
        _log.warning("часть локальных таблиц не прочиталась — метку дельты НЕ двигаю, "
                     "правки уедут следующим циклом")
    else:
        set_push_watermark(mark)
    _session.full_push_done = True
    _session.push_cycles += 1

    #🔥 ОТВЕРГНУТЫЕ СЕРВЕРОМ ЗАПИСИ. Сервер построчно проверяет права преподавателя и
    #возвращает `rejected: {таблица: сколько}` — но этот ответ НЕ ЧИТАЛСЯ НИКЕМ, и
    #расхождение выглядело как полный успех. Цена молчания здесь максимальная: push
    #«удался», водяной знак уехал вперёд, и отвергнутая оценка больше в дельту не
    #попадает — в журнале преподавателя она есть, на сервере её нет, и так навсегда
    #(полный снимок раз в FULL_PUSH_EVERY циклов отправит её снова и получит тот же
    #отказ). Причина отказа штатная и живая: админ снял назначение преподавателя на
    #предмет, пока тот работал офлайн.
    #Молча не проглатываем и не роняем цикл: остальные правки уехали законно, а человеку
    #нужен след — в логе и в `sync_runner.status()`, откуда его берёт индикатор.
    _session.last_rejected = dict(res.get("rejected") or {})
    if _session.last_rejected:
        _log.warning("сервер отклонил часть правок (нет прав на эти предмет/группу): %s. "
                     "Они останутся только на этом ПК, пока админ не вернёт назначение.",
                     _session.last_rejected)

    #2. Тянем ДЕЛЬТУ: только изменения позже метки last_sync — это снимает главный
    #тормоз (раньше каждый цикл качал всю базу). Первый pull сессии — полный
    #(since=""), для самоизлечения; последующие — по сохранённой метке.
    since = "" if not _session.full_pull_done else get_sync_watermark()
    data = client.pull(since=since)
    apply_remote(data.get("changes", {}))

    #3. Сдвигаем метку на server_time этого pull. Сервер берёт её ДО выборки, поэтому
    #следующая дельта не пропустит записи, появившиеся во время текущего запроса.
    server_time = data.get("server_time", "")
    if server_time:
        set_sync_watermark(server_time)
    else:
        #Метку НЕ выдумываем: подставить локальное «сейчас» было бы опасно — часы клиента
        #и сервера расходятся, и при спешащих часах следующая дельта ПРОПУСТИЛА бы записи
        #(потеря данных). Оставляем прежнюю: повторный pull идемпотентен, лишний трафик —
        #единственная плата. Но молчать нельзя: это дефект контракта сервера.
        _log.warning("pull без server_time — метка дельты не сдвинута, следующий цикл "
                     "заберёт те же изменения повторно")
    _session.full_pull_done = True
    return True
