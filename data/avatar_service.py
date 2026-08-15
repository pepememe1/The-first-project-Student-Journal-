"""
avatar_service.py — разрешение ШКАЛЫ ОЦЕНИВАНИЯ по назначению препод↔предмет↔группа.

🔥 ИМЯ МОДУЛЯ УСТАРЕЛО, И ЭТО НЕ ПРИДИРКА. Он назывался «аватарка пользователя
(десктоп)» и держал профиль: аватар, «О себе», цвет плашки, шкалу оценивания — плюс
локальный кэш этого всего на общем ПК колледжа. Ни одной из тех функций больше нет:
профиль целиком живёт в вебе (`/me/prefs` + `web/src/stores/profile.js`), а
их единственными вызывающими были нативные Qt-экраны, удалённые вместе с оболочкой.
Вырезаны `get_avatar`, `save_avatar`, `get_bio`, `get_profile_color`,
`get_grading_scale`, `save_grading_scale`, `save_profile` и вся обвязка локального кэша
(`_ident_token`/`_key`/`_synced_pref`/`_synced_avatar`, константа `BIO_LIMIT`).
Шапка при этом ссылалась на `theme_service` — модуль, которого в репозитории нет вовсе.

⚠️ Переименовать файл — ОТДЕЛЬНАЯ правка, не эта: имя `avatar_service` зашито в
`vector/intents.py` (два места) и в сборочные скрипты, и менять его заодно с уборкой
значило бы смешать два разных изменения в одном заходе.

⚠️ И честно про достижимость того, что осталось: единственный вызывающий
`get_subject_grading_scale` — `vector/intents.py`, то есть НАТИВНЫЙ офлайн-Вектор
десктопа. У самого пакета `vector/` вызывающих в продукте сегодня нет (окно программы
показывает ту же SPA, а её Вектор обслуживает `server/app/routers/web/vector.py`).
Функция рабочая и покрыта тестами, но считать её «тем, что крутится у людей», нельзя.
"""


def get_subject_grading_scale(group: str, subject: str, year: str = "", semester=None) -> str:
    """Шкала преподавателя, ВЕДУЩЕГО (группа,предмет) — для журнала/экспорта СТУДЕНТА
    (тот смотрит чужой предмет, не свой). Разрешение через то же назначение препод↔
    предмет↔группа (data_store.get_subject_teacher_id), что и на сервере
    (webdata.lesson_scale_map) — единый источник, не отдельная копия. Без назначения
    или у назначенного препода нет своей строки в локальных teachers — "5"."""
    import grading
    from data.data_store import get_store
    try:
        store = get_store()
        tid = store.get_subject_teacher_id(group, subject, year, semester)
        if not tid:
            return grading.DEFAULT_SCALE
        for rec in store.get_teachers().values():
            if rec.get("id") == tid:
                sc = (rec.get("prefs") or {}).get("grading_scale") or grading.DEFAULT_SCALE
                return sc if sc in grading.SCALES else grading.DEFAULT_SCALE
    except Exception as e:
        #Шкала — оформление ввода, а не сама оценка: уронить из-за неё журнал нельзя.
        #Но и молчать нельзя — раньше здесь стоял голый `pass`, и «у всех вдруг стала
        #пятибалльная» выглядело как решение продукта, а не как сбой чтения базы.
        import log
        log.get("avatar_service").warning(
            f"[scale] не удалось определить шкалу для {group!r}/{subject!r}: {e} — "
            f"беру умолчание")
    return grading.DEFAULT_SCALE
