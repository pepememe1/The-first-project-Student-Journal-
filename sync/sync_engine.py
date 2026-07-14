"""
sync_engine.py — Слой-переходник offline-first синхронизации (вариант А).

Зачем: модели данных десктопа и сервера НЕ совпадают. Десктоп хранит студентов,
преподавателей и группы как JSON-списки/словари в kv_store, а бэкенд — как
отдельные строки (users/groups/subjects/...). Этот модуль переводит одно в другое
в обе стороны, чтобы прога продолжала хранить данные как раньше, а на сервер
уходил/приходил формат API.

Принцип: здесь ТОЛЬКО перевод и оркестрация. Локальное хранилище — по-прежнему
через data_store/DBManager (offline-first не ломаем). Сетевой обмен — через
sync_client. Любая сетевая ошибка не критична: синк откладывается, прога работает.

Ниже «чистые» функции перевода (без БД и без сети) — их легко тестировать
прогонкой round-trip через сервер. Класс SyncEngine связывает их с локальным
хранилищем и клиентом (его проводка в жизненный цикл приложения — отдельный шаг).
"""
from datetime import datetime, timezone


def _now() -> str:
    #UTC + микросекунды (единый формат с сервером и data_store._now_iso) —
    #чтобы LWW-сравнение строк не зависело от часового пояса клиента.
    return datetime.now(timezone.utc).isoformat()


def _should_apply(inc_ts: str, cur_ts: str, inc_deleted: bool) -> bool:
    """LWW с tie-break: применяем, если входящая метка позже; при РАВНОЙ метке —
    применяем только удаление (надгробие не должно «воскресать» из-за устаревшего
    живого пуша с той же меткой)."""
    if inc_ts > cur_ts:
        return True
    return inc_ts == cur_ts and bool(inc_deleted)


#Стабильные идентификаторы сущностей (нужны для upsert на сервере)
def _student_id(s: dict) -> str:
    login = (s.get("login") or "").strip()
    if login:
        return f"stud:{login}"
    return f"stud:{s.get('surname','')}|{s.get('name','')}|{s.get('group','')}"


def _teacher_id(fullname: str, data: dict) -> str:
    login = (data.get("login") or "").strip()
    return f"teach:{login}" if login else f"teach:{fullname}"


#Студенты  <->  users(role=student)
def students_to_users(students: list) -> list:
    out = []
    for s in students:
        out.append({
            "id": _student_id(s), "role": "student",
            "login": s.get("login", ""), "password_hash": s.get("password_hash", ""),
            "surname": s.get("surname", ""), "name": s.get("name", ""),
            "group_name": s.get("group", ""), "full_name": "",
            "subjects": [], "group_assignments": {},
            "updated_at": s.get("updated_at", "") or _now(),
            "deleted": bool(s.get("deleted", False)),
        })
    return out


#Преподаватели (dict {ФИО: data})  ↔  users(role=teacher)
def teachers_to_users(teachers: dict) -> list:
    out = []
    for fullname, d in teachers.items():
        out.append({
            "id": _teacher_id(fullname, d), "role": "teacher",
            "login": (d.get("login") or ""), "password_hash": d.get("password_hash", ""),
            "full_name": fullname, "surname": "", "name": "", "group_name": "",
            "subjects": d.get("subjects", []) or [],
            "group_assignments": d.get("group_assignments", {}) or {},
            "updated_at": d.get("updated_at", "") or _now(),
            "deleted": bool(d.get("deleted", False)),
        })
    return out


#  Группы (list)  <->  groups
def groups_to_rows(groups: list) -> list:
    return [{
        "id": f"grp:{g.get('name','')}", "name": g.get("name", ""),
        "subjects": g.get("subjects", []) or [],
        "updated_at": g.get("updated_at", "") or _now(),
        "deleted": bool(g.get("deleted", False)),
    } for g in groups]


#Предметы (list имён)  <->  subjects
def subjects_to_rows(names: list) -> list:
    return [{"id": f"subj:{n}", "name": n, "updated_at": _now(), "deleted": False}
            for n in names if n]


def rows_to_subjects(rows: list) -> list:
    return sorted({r.get("name", "") for r in rows
                   if not r.get("deleted") and r.get("name")})


#Конфиг + админ
#admin_password_hash уезжает как пользователь role=admin; остальные ключи — в config.

def admin_user_from_config(cfg: dict, admin_login: str = "admin") -> dict:
    h = cfg.get("admin_password_hash")
    if not h:
        return None
    return {
        "id": f"admin:{admin_login}", "role": "admin", "login": admin_login,
        "password_hash": h, "full_name": "Администратор",
        "surname": "", "name": "", "group_name": "",
        "subjects": [], "group_assignments": {},
        "updated_at": cfg.get("admin_updated_at", "") or _now(), "deleted": False,
    }


def config_to_rows(cfg: dict) -> list:
    rows = []
    for k, v in cfg.items():
        if k == "admin_password_hash":   #уезжает как admin-пользователь
            continue
        rows.append({"key": k, "value": v, "updated_at": _now(), "deleted": False})
    return rows


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
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    #Шлём ВСЕ занятия, включая надгробия (deleted=1) — иначе удаление не доедет до
    #других ПК и занятие воскреснет на следующем pull.
    cur.execute("SELECT id,group_name,subject,type,number,topic,date,"
                "retake_date,hour,COALESCE(updated_at,''),COALESCE(deleted,0) FROM lessons")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "group_name": r[1], "subject": r[2], "type": r[3],
            "number": r[4], "topic": r[5], "date": r[6], "retake_date": r[7],
            "hour": r[8], "extra": {}, "updated_at": r[9] or _now(),
            "deleted": bool(r[10]),
        })
    return out


def _collect_grades() -> list:
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    #Шлём ВСЕ оценки, включая надгробия (deleted=1) — чтобы удаление оценки
    #распространилось, а не «воскресло» при следующем pull.
    cur.execute("SELECT student_f,student_n,lesson_id,grade,"
                "COALESCE(updated_at,''),COALESCE(device,''),COALESCE(deleted,0) FROM grades")
    rows = cur.fetchall()
    conn.close()
    out = []
    for f, n, lid, grade, uat, dev, deleted in rows:
        out.append({
            "id": f"{f}|{n}|{lid}", "student_f": f, "student_n": n, "lesson_id": lid,
            "grade": grade, "device": dev, "updated_at": uat or _now(),
            "deleted": bool(deleted),
        })
    return out


def _collect_term_grades() -> list:
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    #Шлём ВСЕ итоговые оценки, включая надгробия (deleted=1) — иначе снятие оценки
    #не доедет до других ПК/сайта и она «воскреснет» на следующем pull.
    cur.execute("SELECT id,student_f,student_n,subject,COALESCE(year,''),"
                "COALESCE(semester,0),COALESCE(grade,''),COALESCE(form,''),"
                "COALESCE(updated_at,''),COALESCE(deleted,0) FROM term_grades")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "student_f": r[1], "student_n": r[2], "subject": r[3],
            "year": r[4], "semester": r[5], "grade": r[6], "form": r[7],
            "updated_at": r[8] or _now(), "deleted": bool(r[9]),
        })
    return out


def collect_local() -> dict:
    """Читает всё локальное состояние и переводит в формат API (для push)."""
    from data_store import get_store
    from subjects import load_subjects
    st = get_store()
    cfg = st._config()
    #raw — со «надгробиями», чтобы удаления тоже уезжали на сервер
    users = students_to_users(st.get_students_raw()) + teachers_to_users(st.get_teachers_raw())
    admin = admin_user_from_config(cfg, st.get_admin_login())
    if admin:
        users.append(admin)
    return {
        "users": users,
        "groups": groups_to_rows(st.get_groups_raw()),
        "subjects": subjects_to_rows(load_subjects()),
        "config": config_to_rows(cfg),
        "lessons": _collect_lessons(),
        "grades": _collect_grades(),
        "term_grades": _collect_term_grades(),
    }


def _merge_by_key(local_list: list, remote_list: list, key_fn) -> list:
    """Слияние двух списков по ключу: побеждает запись с более поздним updated_at.
    Надгробия (deleted=True) СОХРАНЯЕМ — они должны храниться локально и дальше
    распространяться, иначе удалённая запись «воскреснет» на других ПК."""
    m = {key_fn(r): r for r in local_list}
    for r in remote_list:
        k = key_fn(r)
        loc = m.get(k)
        if loc is None or _should_apply(r.get("updated_at", ""),
                                        loc.get("updated_at", ""), r.get("deleted")):
            m[k] = r
    return list(m.values())


def apply_remote(changes: dict):
    """Применяет пришедшие с сервера изменения в локальное хранилище (LWW-слияние).
    Пишем с stamp=False — сохраняем серверные метки, чтобы синк не зациклился."""
    from data_store import get_store, _kv_set, _student_key
    from subjects import load_subjects, save_subjects
    st = get_store()
    users = changes.get("users", []) or []

    #Студенты (с надгробиями: deleted-записи переносим как есть для LWW-слияния)
    if users:
        rem_s = [{
            "surname": u.get("surname", ""), "name": u.get("name", ""),
            "group": u.get("group_name", ""), "login": u.get("login", ""),
            "password_hash": u.get("password_hash", ""),
            "prefs": u.get("prefs") or {},   #тема оформления приезжает с сервера
            "updated_at": u.get("updated_at", ""), "deleted": bool(u.get("deleted", False)),
        } for u in users if u.get("role") == "student"]
        merged_s = _merge_by_key(st.get_students_raw(), rem_s, _student_key)
        #wake=False: это применение серверных данных, не локальная правка — будить
        #синк не нужно (иначе apply_remote зациклил бы синхронизацию сам на себя).
        st.set_students(merged_s, stamp=False, wake=False)

        #Преподаватели (dict <-> список для слияния)
        loc_t = [dict(v, full_name=k) for k, v in st.get_teachers_raw().items()]
        rem_t = [{
            "full_name": u.get("full_name", ""), "login": u.get("login", ""),
            "password_hash": u.get("password_hash", ""),
            "subjects": u.get("subjects") or [],
            "group_assignments": u.get("group_assignments") or {},
            "prefs": u.get("prefs") or {},   #тема оформления приезжает с сервера
            "updated_at": u.get("updated_at", ""), "deleted": bool(u.get("deleted", False)),
        } for u in users if u.get("role") == "teacher"]
        merged_t = _merge_by_key(loc_t, rem_t, lambda r: r.get("full_name", ""))
        teachers = {r.pop("full_name"): r for r in merged_t}
        st.set_teachers(teachers, stamp=False, wake=False)

    #Группы (с надгробиями)
    if "groups" in changes:
        rem_g = [{"name": r.get("name", ""), "subjects": r.get("subjects") or [],
                  "updated_at": r.get("updated_at", ""), "deleted": bool(r.get("deleted", False))}
                 for r in changes["groups"]]
        merged_g = _merge_by_key(st.get_groups_raw(), rem_g, lambda r: r.get("name", ""))
        st.set_groups(merged_g, stamp=False, wake=False)

    #Предметы (объединение множеств)
    if "subjects" in changes:
        cur = set(load_subjects())
        save_subjects(sorted(cur | set(rows_to_subjects(changes["subjects"]))))

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


def _merge_lessons(remote: list):
    from core import DBManager
    conn = DBManager.get_conn()
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
            "(id,group_name,subject,type,number,topic,date,retake_date,hour,updated_at,deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (lid, l.get("group_name", ""), l.get("subject", ""), l.get("type", ""),
             l.get("number", 0), l.get("topic", ""), l.get("date", ""),
             l.get("retake_date", ""), l.get("hour", 0), l.get("updated_at", ""),
             1 if rdel else 0))
    conn.commit()
    conn.close()


def _merge_grades(remote: list):
    """Слияние оценок с сервера. Оценки — чувствительные данные, поэтому здесь НЕ
    слепой LWW, а детектор конфликтов: если серверное значение оценки расходится
    с локальным и локальное не новее — расхождение пишем в sync_conflicts и НЕ
    затираем работу преподавателя (он решит вручную через conflict_dialog).
    Если значения совпали или локальное новее — конфликта нет."""
    from core import DBManager
    conn = DBManager.get_conn()
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
            if lat and rat and lat > rat:
                continue                       #локальная правка новее — оставляем
            cur.execute("UPDATE grades SET deleted=1, updated_at=?, device=? "
                        "WHERE student_f=? AND student_n=? AND lesson_id=?",
                        (rat, rdev, f, n, lid))
            continue

        #Активная оценка с сервера.
        if local is None:
            #Локально такой оценки нет — просто принимаем серверную.
            cur.execute(
                "INSERT OR REPLACE INTO grades "
                "(student_f,student_n,lesson_id,grade,updated_at,device,deleted) "
                "VALUES (?,?,?,?,?,?,0)", (f, n, lid, rgrade, rat, rdev))
            continue
        lgrade, lat, ldel = local
        if ldel:
            #Локально оценка была удалена, а с сервера пришла активная (её
            #восстановили на другом ПК). Применяем, если серверная не старше нашего
            #надгробия — иначе наше удаление новее и уедет на сервер.
            if not (lat and rat and lat > rat):
                cur.execute(
                    "INSERT OR REPLACE INTO grades "
                    "(student_f,student_n,lesson_id,grade,updated_at,device,deleted) "
                    "VALUES (?,?,?,?,?,?,0)", (f, n, lid, rgrade, rat, rdev))
            continue
        if (lgrade or "") == (rgrade or ""):
            continue   #значения совпали — менять нечего
        if lat and rat and lat > rat:
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
    conn.commit()
    conn.close()


def _merge_term_grades(remote: list):
    """Слияние итоговых оценок (аттестации) с сервера — простой LWW с tie-break
    (как занятия). Диалог конфликтов тут не нужен: это одна итоговая оценка за
    семестр, а не «два разных балла за занятие» — побеждает более поздняя правка."""
    from core import DBManager
    conn = DBManager.get_conn()
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
            "(id,student_f,student_n,subject,year,semester,grade,form,updated_at,deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (gid, g.get("student_f", ""), g.get("student_n", ""), g.get("subject", ""),
             g.get("year", ""), int(g.get("semester", 0) or 0), g.get("grade", ""),
             g.get("form", ""), g.get("updated_at", ""), 1 if rdel else 0))
    conn.commit()
    conn.close()


#Флаг «первый синк этой сессии». На старте процесса делаем ОДИН полный pull
#(since=""), даже если метка уже есть: так лечится возможный дрейф — редкая потеря
#пограничной записи из-за гонки «коммит против взятия метки». Дальше в течение
#сессии тянем только дельту. Поток синка один, поэтому простого флага достаточно.
_session_full_pull_done = False


def force_full_pull():
    """Сбрасывает флаг «полный pull сессии уже сделан», чтобы СЛЕДУЮЩИЙ sync_once
    тянул всё с сервера (since=""), а не дельту. Нужно после reset_synced_local_data:
    кэш стёрт, и его надо наполнить заново полным снимком сервера."""
    global _session_full_pull_done
    _session_full_pull_done = False


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
    from data_store import reset_synced_local_data
    #Спасаем офлайн-правки: пуш перед очисткой. Ошибку глушим — если сервер вдруг отпал
    #между проверкой доступности и этим вызовом, дальше упадёт pull и вызывающий уйдёт в
    #офлайн-ветку, а несохранённый кэш останется на месте (reset ещё не выполнен).
    try:
        client.push(collect_local())
    except Exception as e:
        print(f"[reconcile] пуш офлайн-правок перед сбросом кэша не удался: {e}")
        raise   #не стираем кэш, если правки не удалось отправить — данные важнее «чистоты»
    reset_synced_local_data()
    force_full_pull()
    return sync_once(client)


def sync_once(client) -> bool:
    """Один цикл синхронизации: отправить локальные изменения, забрать серверные.
    Возвращает True при успехе. Бросаемые сетевые ошибки ловит вызывающий код."""
    global _session_full_pull_done
    from data_store import get_sync_watermark, set_sync_watermark

    #1. Отправляем то, что вправе отправлять (роль ограничивает на сервере).
    #Push — полный снимок и идемпотентен: сервер применит только реально изменённое.
    client.push(collect_local())

    #2. Тянем ДЕЛЬТУ: только изменения позже метки last_sync — это снимает главный
    #тормоз (раньше каждый цикл качал всю базу). Первый pull сессии — полный
    #(since=""), для самоизлечения; последующие — по сохранённой метке.
    since = "" if not _session_full_pull_done else get_sync_watermark()
    data = client.pull(since=since)
    apply_remote(data.get("changes", {}))

    #3. Сдвигаем метку на server_time этого pull. Сервер берёт её ДО выборки, поэтому
    #следующая дельта не пропустит записи, появившиеся во время текущего запроса.
    server_time = data.get("server_time", "")
    if server_time:
        set_sync_watermark(server_time)
    _session_full_pull_done = True
    return True
