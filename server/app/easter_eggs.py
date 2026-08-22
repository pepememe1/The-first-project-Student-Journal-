"""
easter_eggs.py — ачивки и серверный бросок шанса для пасхалок.

Полное ТЗ — `docs/PLAN-EASTER-EGGS.md`. Здесь только инфраструктура: сами пасхалки
живут на клиенте (это визуальные сцены), а сервер отвечает за две вещи, которые
клиенту доверять нельзя.

━━ ПОЧЕМУ ШАНС СЧИТАЕТ СЕРВЕР ━━
`Math.random()` в браузере правится через инструменты разработчика за секунду, и
редкая пасхалка (1/666) перестала бы быть редкой. Плюс бросок должен быть общим для
всех устройств человека: иначе, открыв журнал на телефоне и на ПК, он получал бы два
независимых шанса на одно и то же событие.

━━ ПОЧЕМУ СПРАВОЧНИКА АЧИВОК ТУТ НЕТ ━━
Названия, описания, значки и редкость — статика, и место ей в
`web/src/config/achievements.js`: там она переводится вместе с остальным интерфейсом.
Сервер держит ТОЛЬКО белый список идентификаторов — он нужен, чтобы в публичное поле
«показывать в профиле» нельзя было протащить произвольную строку и показать её другим.
Список ниже обязан совпадать с клиентским; за этим следит `test_achievements.py`.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import EasterEggLog, UserAchievement

_log = logging.getLogger("gradebook.eggs")

#Белый список ачивок. Ключ — id, значение — id пасхалки, которая её выдаёт (для
#читаемости и чтобы не разъехались; на логику не влияет).
ACHIEVEMENTS: dict[str, str] = {
    "cyberpunk_samurai":   "cyberpunk_login",
    "detroit_led":         "detroit_led",
    "fnaf_night":          "fnaf_night_mode",
    "isaac_reroll":        "binding_of_isaac_d6",
    "ultrakill_fuel":      "ultrakill_rank",
    "disco_listen":        "disco_elysium_voice",
    "doom_hud_face":       "doom_avatar",
    "papers_glory":        "papers_please_stamp",
    "undertale_resolve":   "undertale_save",
    "portal_cake_lie":     "portal_cake",
    "hotline_50":          "hotline_miami",
    "gman_observer":       "gman_observer",
    "stanley_427":         "stanley_parable_404",
    "darksouls_session":   "dark_souls_logout",
    "deltarune_egg":       "deltarune_tree",
}
ACHIEVEMENT_IDS = frozenset(ACHIEVEMENTS)

#Шансы: знаменатель, то есть 666 — это «один раз из 666». Отдельным словарём, чтобы
#балансировать частоту, не трогая логику.
EGG_CHANCES: dict[str, int] = {
    "deltarune_tree":       666,
    "binding_of_isaac_d6":  500,
    "gman_observer":        200,
    "undertale_save":       100,
    "detroit_led":          100,
    "fnaf_night_mode":       87,
    "hotline_miami":         89,
    "disco_elysium_voice":   80,
    "cyberpunk_login":       77,
    "papers_please_stamp":   50,
    "stanley_parable_404":   10,
    "rdr2_404":              10,
    "dark_souls_logout":     40,
    "skyrim_wake_up":         3,      # 30% — уже после серии неудачных входов
    "farcry_vaas_quote":     10,      # 10% — на седьмой неудаче подряд
}

#Кулдаун: одна и та же пасхалка не показывается человеку чаще раза в сутки. Без него
#редкость перестаёт читаться как редкость — на большой выборке страниц даже 1/500
#срабатывает по нескольку раз за вечер.
COOLDOWN_S = 24 * 60 * 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def roll(egg_id: str, user_id: str, db: Session) -> bool:
    """Бросок для одной пасхалки. True — показываем.

    Неизвестный `egg_id` — всегда False: молча ничего не показываем, но пишем в лог.
    Тихо возвращать False без следа нельзя, иначе опечатка в имени превратится в
    «пасхалка не работает» без единой подсказки почему."""
    chance = EGG_CHANCES.get(egg_id)
    if not chance:
        _log.warning("бросок для неизвестной пасхалки: %s", egg_id)
        return False
    if not user_id:
        return False

    cutoff = int(datetime.now(timezone.utc).timestamp()) - COOLDOWN_S
    recent = (db.query(EasterEggLog)
                .filter(EasterEggLog.user_id == user_id,
                        EasterEggLog.egg_id == egg_id,
                        EasterEggLog.created_ts >= cutoff)
                .first())
    if recent:
        return False

    if random.randint(1, chance) != 1:
        return False

    db.add(EasterEggLog(user_id=user_id, egg_id=egg_id, triggered_at=_now_iso(),
                        created_ts=int(datetime.now(timezone.utc).timestamp())))
    db.commit()
    return True


def roll_one_of(egg_ids: list[str], user_id: str, db: Session) -> str | None:
    """Первая сработавшая из набора — и на этом останавливаемся.

    Нужна там, где на одной странице конкурируют несколько пасхалок (дневник оценок,
    страница 404): без этого на одной загрузке могли бы вылезти сразу две, и обе
    перестали бы читаться как редкая находка. Порядок перебора случайный, иначе
    первая в списке всегда имела бы преимущество."""
    order = list(egg_ids)
    random.shuffle(order)
    for egg_id in order:
        if roll(egg_id, user_id, db):
            return egg_id
    return None


def unlock(user_id: str, achievement_id: str, db: Session) -> bool:
    """Открыть ачивку. True — открыли только что, False — уже была или id неизвестен.

    ⚠️ Зовётся ТОЛЬКО из серверной логики. Ручки «выдай мне ачивку» с фронта нет и
    быть не должно: иначе их накрутят одним curl'ом, и весь список обесценится."""
    if achievement_id not in ACHIEVEMENT_IDS:
        _log.warning("попытка выдать неизвестную ачивку: %s", achievement_id)
        return False
    exists = (db.query(UserAchievement)
                .filter(UserAchievement.user_id == user_id,
                        UserAchievement.achievement_id == achievement_id)
                .first())
    if exists:
        return False
    db.add(UserAchievement(user_id=user_id, achievement_id=achievement_id,
                           unlocked_at=_now_iso(), showcase=False))
    db.commit()
    return True


def unlocked_ids(user_id: str, db: Session) -> list[str]:
    rows = db.query(UserAchievement).filter(UserAchievement.user_id == user_id).all()
    return [r.achievement_id for r in rows]


def showcase_ids(user_id: str, db: Session) -> list[str]:
    """Что человек сам решил показать в своём профиле другим."""
    rows = (db.query(UserAchievement)
              .filter(UserAchievement.user_id == user_id,
                      UserAchievement.showcase == True)          # noqa: E712
              .all())
    return [r.achievement_id for r in rows]
