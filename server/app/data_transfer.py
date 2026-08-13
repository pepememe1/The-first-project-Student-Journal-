"""
data_transfer.py — выгрузка и загрузка данных журнала (админка): ZIP с наборами данных
по отдельности + ВЫБОРОЧНЫЙ импорт по галочкам.

━━ ЗАЧЕМ ОДИН МОДУЛЬ НА ДВЕ ЗАДАЧИ ━━
«Резервная копия» и «экспорт данных» в этой системе — одно и то же действие: полный слепок
справочников и журнала в читаемом виде. Отдельная реализация бэкапа означала бы второй
формат, который надо отдельно проверять на восстановимость. Здесь один формат, и то, что
скачано «на всякий случай», гарантированно принимается импортом обратно.

━━ ФОРМАТ ━━
ZIP, внутри — по файлу на набор данных (`students.json`, `groups.json`, …) плюс
`manifest.json` (что внутри, сколько записей, версия, когда снято). JSON, а не CSV:
у части полей значения — списки и словари (`Group.subjects`, `ConfigKV.value`), и CSV их
пришлось бы кодировать самодельно. Файлы ПО ОТДЕЛЬНОСТИ — чтобы импортировать можно было
часть (например, только студентов), не трогая остальное.

━━ ЧЕГО ЗДЕСЬ НЕТ ОСОЗНАННО ━━
• ПАРОЛЕЙ. `password_hash` в выгрузку не попадает никогда (`_SECRET_FIELDS`): архив
  скачивается на рабочий компьютер, ходит по почте и попадает в облака, а хеш — это
  предмет атаки офлайн-перебором. Обратная сторона: восстановление из архива НЕ вернёт
  пароли, и это указано в манифесте, чтобы никто не рассчитывал на обратное.
• ПЕРЕПИСКИ мессенджера. Она не входит в синк и не является справочными данными; выгружать
  чужие личные сообщения «за компанию» с журналом нельзя.
• АВТОМАТИЧЕСКОГО ПРИМЕНЕНИЯ. Импорт всегда сначала показывает, что в файле (`inspect`),
  и лишь потом пишет — и только то, что отметили.
"""
import io
import json
import zipfile
from datetime import datetime, timezone

from .models import SYNC_MODELS, ParentLink

#Наборы данных: понятное имя → (файл в архиве, модель, подпись для интерфейса).
#Порядок значим при импорте: справочники раньше того, что на них ссылается — иначе оценки
#приедут к ещё не существующим занятиям.
DATASETS = (
    ("groups", "groups.json", SYNC_MODELS["groups"], "Группы"),
    ("subjects", "subjects.json", SYNC_MODELS["subjects"], "Предметы"),
    ("teachers", "teachers.json", SYNC_MODELS["users"], "Преподаватели"),
    ("students", "students.json", SYNC_MODELS["users"], "Студенты"),
    ("parents", "parents.json", SYNC_MODELS["users"], "Родители"),
    ("parent_links", "parent_links.json", ParentLink, "Связи родитель—студент"),
    ("subject_hours", "subject_hours.json", SYNC_MODELS["subject_hours"],
     "Учебные часы по предметам"),
    ("lessons", "lessons.json", SYNC_MODELS["lessons"], "Занятия"),
    ("grades", "grades.json", SYNC_MODELS["grades"], "Оценки"),
    ("term_grades", "term_grades.json", SYNC_MODELS["term_grades"], "Итоговые оценки"),
    ("schedule_overrides", "schedule_overrides.json", SYNC_MODELS["schedule_overrides"],
     "Правки расписания"),
    ("config", "config.json", SYNC_MODELS["config"], "Настройки"),
)

#Роль, по которой отбираются пользователи для набора (у трёх наборов одна модель `User`).
_ROLE_OF = {"teachers": "teacher", "students": "student", "parents": "parent"}

#Поля, которые НИКОГДА не покидают сервер (см. шапку). Проверяется на выгрузке И на приёме:
#подсунутый в архив хеш не должен попасть в базу этим путём.
_SECRET_FIELDS = {"password_hash"}

FORMAT_VERSION = 1


def _row_to_dict(row, model) -> dict:
    """Строка ORM → словарь, без секретов и без служебных полей SQLAlchemy."""
    out = {}
    for col in model.__table__.columns:
        if col.name in _SECRET_FIELDS:
            continue
        out[col.name] = getattr(row, col.name, None)
    return out


def _query(db, name, model):
    """Строки набора. Удалённые (надгробия синка) не выгружаем: в архиве нужны данные, а
    не история удалений — иначе импорт «восстановил» бы удалённых студентов как удалённых."""
    q = db.query(model)
    role = _ROLE_OF.get(name)
    if role is not None:
        q = q.filter(model.role == role)
    if hasattr(model, "deleted"):
        q = q.filter(model.deleted == False)        # noqa: E712
    return q.all()


def export_zip(db, picked=None) -> bytes:
    """Собрать ZIP с выбранными наборами (по умолчанию — со всеми).

    Возвращает БАЙТЫ, а не путь к файлу: архив отдаётся ответом на запрос и на диске
    сервера ему делать нечего (лишняя копия ПДн, которую потом кто-то забудет удалить)."""
    want = set(picked) if picked else {n for n, _f, _m, _l in DATASETS}
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, fname, model, _label in DATASETS:
            if name not in want:
                continue
            rows = [_row_to_dict(r, model) for r in _query(db, name, model)]
            counts[name] = len(rows)
            z.writestr(fname, json.dumps(rows, ensure_ascii=False, indent=1))
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "datasets": counts,
            "labels": {n: l for n, _f, _m, l in DATASETS if n in counts},
            #Прямо в архиве, а не только в интерфейсе: файл переживёт эту страницу.
            "note": ("Пароли в выгрузку не входят — после восстановления их нужно задать "
                     "заново. Личная переписка мессенджера не выгружается."),
        }
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return buf.getvalue()


def inspect_zip(blob: bytes) -> dict:
    """Что лежит в присланном архиве — БЕЗ записи в базу.

    Нужен отдельным шагом: администратор должен увидеть состав файла и отметить галочками,
    что именно вливать. Импорт «сразу как открыли» — это молчаливая перезапись боевых
    данных по одному клику."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except Exception:
        #from None — администратору нужна одна понятная строка, а не цепочка из
        #внутренностей zipfile поверх неё.
        raise ValueError("Это не ZIP-архив выгрузки.") from None
    names = set(z.namelist())
    manifest = {}
    if "manifest.json" in names:
        try:
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        except Exception:
            manifest = {}
    found = []
    for name, fname, _model, label in DATASETS:
        if fname not in names:
            continue
        try:
            rows = json.loads(z.read(fname).decode("utf-8"))
        except Exception:
            #Битый файл внутри архива не должен прятать остальные наборы.
            found.append({"name": name, "label": label, "count": 0,
                          "error": "файл повреждён"})
            continue
        found.append({"name": name, "label": label,
                      "count": len(rows) if isinstance(rows, list) else 0, "error": ""})
    if not found:
        raise ValueError("В архиве нет ни одного известного набора данных.")
    return {"format": manifest.get("format", 0),
            "created_at": manifest.get("created_at", ""),
            "note": manifest.get("note", ""),
            "datasets": found}


def import_zip(db, blob: bytes, picked, now_iso: str) -> dict:
    """Влить ОТМЕЧЕННЫЕ наборы. Возвращает {набор: сколько записей} и список замечаний.

    ⚠️ Слияние по первичному ключу (merge), а не «очистить и залить»: архив мог быть снят
    до появления новых записей, и очистка стёрла бы то, чего в файле просто нет.

    ⚠️ Метку `updated_at` ставит СЕРВЕР — тем же правилом, что и синк (§4.3). Иначе
    восстановление из старого архива приехало бы с давними метками, и LWW на десктопах
    счёл бы эти записи устаревшими: данные вернулись бы на сервер и тут же «проиграли» бы
    локальным копиям. Секреты (`password_hash`) не принимаются даже если лежат в файле."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = set(z.namelist())
    want = set(picked or ())
    written = {}
    notes = []
    for name, fname, model, label in DATASETS:
        if name not in want or fname not in names:
            continue
        try:
            rows = json.loads(z.read(fname).decode("utf-8"))
        except Exception:
            notes.append(f"{label}: файл повреждён, пропущен")
            continue
        if not isinstance(rows, list):
            notes.append(f"{label}: неожиданный формат, пропущен")
            continue
        cols = {c.name for c in model.__table__.columns}
        count = 0
        for raw in rows:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue        #без первичного ключа сливать некуда
            data = {k: v for k, v in raw.items()
                    if k in cols and k not in _SECRET_FIELDS}
            #Роль набора важнее того, что написано в файле: иначе подменённый файл
            #«студентов» мог бы завести администратора.
            role = _ROLE_OF.get(name)
            if role is not None:
                data["role"] = role
            if "updated_at" in cols:
                data["updated_at"] = now_iso
            if "deleted" in cols:
                data["deleted"] = False
            existing = db.get(model, data["id"])
            if existing is not None and "password_hash" in cols:
                #Пароля в архиве нет — сохраняем уже имеющийся. Без этого восстановление
                #справочника обнулило бы вход существующим людям (ровно та авария, что
                #однажды случилась на бою через синк).
                data["password_hash"] = getattr(existing, "password_hash", "") or ""
            db.merge(model(**data))
            count += 1
        written[name] = count
    db.commit()
    return {"written": written, "notes": notes}
