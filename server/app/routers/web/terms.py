"""
terms.py — Учебный период: список термина/архива и перевод на следующий семестр.

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы


# УЧЕБНЫЙ ПЕРИОД (год/семестр) ───────────────────────────────────────────────────
@router.get("/terms")
def terms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Доступные учебные периоды (для селектора/архива) + текущий термин."""
    cfg = W.load_config(db)
    cy, cs = W.current_term(cfg)
    return {"current": {"year": cy, "semester": cs}, "terms": W.list_terms(db)}


@router.post("/admin/term/rollover")
def admin_term_rollover(payload: dict = Body(default={}), request: Request = None,
                        _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Перевод на следующий учебный период (перевод на курс).

    Продвигает ТЕКУЩИЙ термин: семестр 1→2 (тот же год) или 2→1 (год +1). Прошлые
    занятия остаются в своём периоде и становятся read-only (архив, см. _ensure_current_term).
    Ростер/группы НЕ трогаем — новый семестр наполняется занятиями заново. Можно задать
    явные year+semester в теле. Текущий термин хранится в config (синкается на десктоп)."""
    cfg = W.load_config(db)
    cy, cs = W.current_term(cfg)
    ny = (payload.get("year") or "").strip()
    ns = payload.get("semester")
    if ny and ns:
        new_year, new_sem = ny, int(ns)
    elif cs == 1:
        new_year, new_sem = cy, 2                 #осень → весна того же года
    else:
        try:                                      #весна → осень следующего года
            a, b = cy.split("/")
            new_year = f"{int(a) + 1}/{int(b) + 1}"
        except Exception:
            new_year = cy
        new_sem = 1
    row = db.get(ConfigKV, "config")
    cur = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    cur["current_year"] = new_year
    cur["current_semester"] = new_sem
    now = _now_iso()
    if row is None:
        db.add(ConfigKV(key="config", value=cur, updated_at=now, deleted=False))
    else:
        row.value = cur
        row.updated_at = now
    db.commit()
    audit.log(db, request, actor=_admin.login, role="admin", action="term.rollover",
              detail=f"{cy}·{cs} → {new_year}·{new_sem}")
    #§12: отчёты куратора «вечны» (кнопки не удаляются), но после rollover'а старого
    #термина архивируются — новый /отчет уже не берёт значения из term'а, который
    #только что закрылся. Сбой этой пометки не должен ломать сам rollover.
    try:
        from ...models import CuratorReport
        (db.query(CuratorReport)
         .filter(CuratorReport.year == cy, CuratorReport.semester == cs,
                 CuratorReport.archived == False)  # noqa: E712
         .update({"archived": True}, synchronize_session=False))
        db.commit()
    except Exception as e:
        print(f"[curator_reports] не удалось архивировать отчёты term {cy}·{cs}: {e}")
    return {"ok": True, "previous": {"year": cy, "semester": cs},
            "current": {"year": new_year, "semester": new_sem}}
