"""
achievements.py — ачивки за пасхалки: свои, витрина в профиле, чужая витрина.

Часть пакета `routers/web` (разрез 3.6). Общий роутер и проверки — в `_common.py`.

━━ ЧТО ЗДЕСЬ ЕСТЬ И ЧЕГО НЕТ ━━
Есть чтение своего списка, переключение «показывать в профиле» и чтение ЧУЖОЙ витрины.
Ручки «выдай мне ачивку» НЕТ и быть не должно: ачивку открывает только серверная
логика самой пасхалки (`easter_eggs.unlock`). Дай её фронту — и весь список
накрутят одним curl'ом, а вместе с ним обесценится и витрина в профиле.

━━ ЧТО ВИДНО ЧУЖОМУ ━━
Только то, что человек сам отметил галочкой. Полный список своих ачивок наружу не
уходит: он показывает, чего у человека НЕТ, а это уже про его поведение в продукте.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы

from ... import easter_eggs


@router.get("/achievements")
def my_achievements(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мои ачивки: что открыто и что из этого показано в профиле.

    Названия и значки НЕ отдаём — они статика и живут на клиенте
    (`web/src/config/achievements.js`), где переводятся вместе с интерфейсом.
    Сервер оперирует только идентификаторами."""
    rows = (db.query(UserAchievement)
              .filter(UserAchievement.user_id == user.id)
              .order_by(UserAchievement.unlocked_at.asc())
              .all())
    return {"unlocked": [{"id": r.achievement_id,
                          "unlocked_at": r.unlocked_at or "",
                          "showcase": bool(r.showcase)} for r in rows],
            "known": sorted(easter_eggs.ACHIEVEMENT_IDS)}


@router.post("/achievements/showcase")
def set_showcase(payload: dict = Body(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Отметить, какие ачивки показывать другим. Приходит ПОЛНЫЙ список отмеченных.

    ⚠️ Отметить можно только СВОЮ открытую ачивку. Присланные чужие или ещё не
    открытые id молча отбрасываются, а не создают строку: витрина — публичное поле,
    и через неё нельзя показать то, чего человек не получал."""
    want = payload.get("ids")
    want = {str(x) for x in want} if isinstance(want, list) else set()
    rows = db.query(UserAchievement).filter(UserAchievement.user_id == user.id).all()
    for r in rows:
        r.showcase = r.achievement_id in want
    db.commit()
    return {"ok": True, "showcase": [r.achievement_id for r in rows if r.showcase]}
