"""
easter_eggs.py — ачивки и серверный бросок шанса для пасхалок.

Полное ТЗ — `docs/PLAN-EASTER-EGGS.md`. Здесь только инфраструктура: сами пасхалки
живут на клиенте (это визуальные сцены), а сервер отвечает за две вещи, которые
клиенту доверять нельзя.

━━ ПОЧЕМУ ШАНС СЧИТАЕТ СЕРВЕР ━━
`Math.random()` в браузере правится через инструменты разработчика за секунду, и
редкая пасхалка (1/500) перестала бы быть редкой. Плюс бросок должен быть общим для
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
from datetime import datetime, timedelta, timezone

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

#Шансы: знаменатель, то есть 500 — это «один раз из 500». Отдельным словарём, чтобы
#балансировать частоту, не трогая логику.
EGG_CHANCES: dict[str, int] = {
    #⚠️ 66, а НЕ 666: решение Влада 23.08.2026. Отсылка к числу сохраняется, но при
    #666 дерево не выпадало практически никому — переключений вкладок за сессию
    #десяток-другой, то есть шанс увидеть его вообще был меньше, чем не увидеть ни разу
    #за весь семестр. Редкость, которой никто не наблюдает, ничем не отличается от
    #отсутствия пасхалки.
    "deltarune_tree":        66,
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

#Кулдаун ПОШТУЧНО, и только там, где он нужен по существу. Ключ — id пасхалки,
#значение — секунды.
#
#⚠️ ЭТО НЕ ВОЗВРАТ СУТОЧНОГО КУЛДАУНА, снятого выше, а решение ОБРАТНОЙ задачи, и
#путать их нельзя. Тот был общий, длинный и невидимый: человек, специально искавший
#пасхалку, не мог понять, не везёт ему или он упёрся в правило. Здесь наоборот —
#дерево Делтарун бросается на КАЖДОЙ смене вкладки, а вкладки переключают десятки раз
#за пару минут. При 1/66 это давало несколько выпадений за сеанс, и находка перестала
#читаться как находка. Пять минут — примерно один показ за занятие.
#
#⚠️ Кулдаун применим ТОЛЬКО к пасхалке с частым триггером. Повесь его на ту, что
#бросается редко (вход, страница 404), и получится ровно та невидимая стена, от которой
#мы избавлялись.
EGG_COOLDOWN_S: dict[str, int] = {
    "deltarune_tree": 300,
}

#⚠️ СУТОЧНОГО КУЛДАУНА БОЛЬШЕ НЕТ (снят 23.08.2026 по решению Влада).
#Он задумывался как страховка «редкость должна читаться как редкость», но на деле
#ограничителем и так работает САМ ШАНС, а кулдаун добавлял вторую, невидимую стену:
#выпала пасхалка один раз — и следующие сутки человек, который специально пытается её
#найти, не понимает, ловит он неудачу или упёрся в правило. Именно на этом Влад и
#споткнулся, пытаясь выбить обе шутки на странице 404.
#
#⚠️ Строку в `EasterEggLog` при этом ПИШЕМ ПО-ПРЕЖНЕМУ, и это не рудимент: на ней
#держится честность ачивок — `claim` выдаёт награду, только если у человека есть свежий
#след срабатывания (`was_triggered_recently`). Убрать запись значило бы сделать `claim`
#обычной ручкой «выдай мне ачивку».


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

    #Кулдаун проверяем ДО броска: иначе шанс тратился бы вхолостую, а на боевой машине
    #это ещё и лишняя запись в базу на каждой смене вкладки.
    cooldown = EGG_COOLDOWN_S.get(egg_id)
    if cooldown and was_triggered_recently(user_id, egg_id, db, within_s=cooldown):
        return False

    if random.randint(1, chance) != 1:
        return False

    db.add(EasterEggLog(user_id=user_id, egg_id=egg_id, triggered_at=_now_iso(),
                        created_ts=int(datetime.now(timezone.utc).timestamp())))
    db.commit()
    return True


def mark_triggered(egg_id: str, user_id: str, db: Session) -> bool:
    """Записать след срабатывания БЕЗ броска — для пасхалок без шанса.

    ⚠️ Нужна ровно там, где условие детерминированное (ULTRAKILL показывается каждому
    отличнику, а не раз в N заходов). Без следа `claim` откажет в ачивке, потому что
    честность ачивок держится именно на нём.

    ⚠️ Звать ТОЛЬКО после проверки условия НА СЕРВЕРЕ. Открытой ручки у этой функции
    нет и быть не должно: `mark_triggered` без условия — это и есть «выдай мне ачивку»,
    от которой защищает вся остальная конструкция."""
    if egg_id not in ACHIEVEMENTS.values():
        _log.warning("след для неизвестной пасхалки: %s", egg_id)
        return False
    if not user_id:
        return False
    db.add(EasterEggLog(user_id=user_id, egg_id=egg_id, triggered_at=_now_iso(),
                        created_ts=int(datetime.now(timezone.utc).timestamp())))
    db.commit()
    return True


#Порог «отличника» для ULTRAKILL. Тот же 4.5, что уже красит продукт в «отличники» у
#куратора (`curator_report.categorize`) — своего набора порогов не заводим, иначе на
#одном экране человек отличник, а на другом нет.
ULTRAKILL_MIN_AVG = 4.5


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

def was_triggered_recently(user_id: str, egg_id: str, db: Session, within_s: int = 3600) -> bool:
    """Срабатывала ли пасхалка у этого человека недавно.

    На этом держится честность ачивок: закрыть находку можно, только если сервер сам
    бросил шанс и он сошёлся. Без такой сверки `claim` превратился бы в «выдай мне
    ачивку», и весь список накрутили бы одним curl'ом."""
    cutoff = int(datetime.now(timezone.utc).timestamp()) - within_s
    return bool(db.query(EasterEggLog)
                  .filter(EasterEggLog.user_id == user_id,
                          EasterEggLog.egg_id == egg_id,
                          EasterEggLog.created_ts >= cutoff)
                  .first())

# ─────────────────────────── УСЛОВИЯ ВХОДА ───────────────────────────
# Всё, что ниже, СПЕЦИАЛЬНО живёт на сервере, а не в браузере: «сейчас ночь», «до этого
# было три неудачных попытки», «сегодня день рождения» — это факты, которые клиент
# подделает одной строкой в консоли. Шанс без честного условия ничего не стоит.

#Улан-Удэ, UTC+8. Ночь считаем по МЕСТНОМУ времени: пасхалка про то, что человек сидит
#в журнале в три часа ночи, а не про то, который час на сервере.
LOCAL_UTC_OFFSET_H = 8


def _local_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=LOCAL_UTC_OFFSET_H)


def _login_attempts(user_login: str, db: Session, limit: int = 12) -> list[bool]:
    """Последние попытки входа: True — удачная. Свежие первыми.

    ⚠️ Отдельной таблицы попыток в проекте НЕТ, и заводить её ради пасхалки не нужно:
    `audit_events` уже пишет `login.ok` и `login.fail` с логином и меткой, и оба поля
    проиндексированы. Счётчики `throttle.py` не подходят — они в ПАМЯТИ процесса и
    переживают ровно до перезапуска."""
    from .models import AuditEvent
    rows = (db.query(AuditEvent)
              .filter(AuditEvent.actor == user_login,
                      AuditEvent.action.in_(("login.ok", "login.fail")))
              .order_by(AuditEvent.created_ts.desc())
              .limit(limit).all())
    return [r.action == "login.ok" for r in rows]


def _fail_streak_before_success(attempts: list[bool]) -> int:
    """Сколько неудач подряд шло ПЕРЕД последней удачной попыткой."""
    if not attempts or not attempts[0]:
        return 0
    n = 0
    for ok in attempts[1:]:
        if ok:
            break
        n += 1
    return n


def is_night(now: datetime = None) -> bool:
    return 0 <= (now or _local_now()).hour < 6


def birthday_today(user, now: datetime = None) -> bool:
    """День рождения — «ДД.ММ», без года: сверяем ровно день и месяц."""
    bd = (getattr(user, "birthday", "") or "").strip()
    if not bd:
        return False
    return bd == (now or _local_now()).strftime("%d.%m")


def pick_on_login(user, db: Session) -> str | None:
    """Что показать сразу после входа. Не больше ОДНОГО за раз.

    Порядок не случайный, он по «громкости»: поздравление с днём рождения адресное и
    бывает раз в год — оно важнее любого шанса; ночная смена меняет весь вход, поэтому
    идёт следом; дальше «наконец-то ты очнулся» — она осмысленна только сразу после
    череды неудач; и лишь потом обычные шансовые."""
    if user.role != "student":
        return None
    if birthday_today(user):
        #⚠️ Без броска — но след ОБЯЗАТЕЛЕН: на нём держится `claim`. Забудь его, и
        #человек увидит торт, а ачивки за него не получит никогда, причём молча.
        mark_triggered("portal_cake", user.id, db)
        return "portal_cake"
    if is_night() and roll("fnaf_night_mode", user.id, db):
        return "fnaf_night_mode"
    if _fail_streak_before_success(_login_attempts(user.login, db)) >= 3 \
            and roll("skyrim_wake_up", user.id, db):
        return "skyrim_wake_up"
    if roll("cyberpunk_login", user.id, db):
        return "cyberpunk_login"
    if roll("detroit_led", user.id, db):
        return "detroit_led"
    return None


def farcry_due(user_login: str, db: Session, user_id: str = "") -> bool:
    """Седьмая неудачная попытка подряд.

    ⚠️ Седьмая, а НЕ восьмая, как было в плане: анти-брутфорс блокирует пару (IP, логин)
    именно на седьмой (`throttle.MAX_FAILS`), и до восьмой проверки пароля дело не
    доходит вовсе — пасхалка не сработала бы ни разу."""
    attempts = _login_attempts(user_login, db)
    streak = 0
    for ok in attempts:
        if ok:
            break
        streak += 1
    if streak < 7:
        return False
    return roll("farcry_vaas_quote", user_id or user_login, db)

