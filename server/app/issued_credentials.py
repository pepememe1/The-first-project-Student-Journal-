# -*- coding: utf-8 -*-
"""issued_credentials.py — стартовые пароли, которые колледж выдаёт студентам (4.0).

━━ ЗАЧЕМ ━━
В начале года администратор (или куратор своей группе) раздаёт список: №, ФИО, логин,
пароль. Выдать бумагу мало — через неделю студент её потеряет, и администратору надо
увидеть тот же пароль ещё раз. Хеш для этого не годится (он необратим), поэтому ВЫДАННЫЙ
колледжем пароль дополнительно хранится шифротекстом в отдельной таблице
(`models.UserIssuedCredential`), недоступной ни синку, ни выгрузке справочников.

━━ ГРАНИЦА, КОТОРУЮ НЕЛЬЗЯ ПЕРЕЙТИ ━━
Пароль, придуманный самим человеком, не виден НИКОМУ и НИКОГДА. Держится это не на том,
что «везде, где меняют пароль, не забыли стереть запись», а на СВЕРКЕ: при выдаче
запоминается отпечаток действовавшего хеша, и при каждом чтении он сравнивается с
текущим (`state`). Хеш другой — значит пароль сменили каким угодно путём (сам в
настройках, по ссылке из письма, синком с пустого узла), и шифротекст стирается сразу,
до того как его успели показать. Путей смены пароля в продукте семь, и восьмой
появится — сверке это безразлично.

⚠️ Явное стирание (`forget`) в местах смены пароля всё равно стоит: без него шифротекст
лежал бы в базе до первого чтения, а базу копируют в резервные копии.

⚠️ Шифр — `gost.encrypt` («Кузнечик» + имитовставка), ТОТ ЖЕ, что у телефонов в заявках.
Своего не заводим. Честная граница: без `GRADEBOOK_DATA_KEY` этот механизм возвращает
текст как есть (так он устроен ради того, чтобы прод не падал до развёртывания СКЗИ), и
тогда пароль лежит открытым текстом внутри базы, зашифрованной SQLCipher целиком. Об этом
говорится громко в журнале событий при каждой выдаче — молчаливое ослабление защиты хуже
отсутствующей.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from . import events, gost
from .models import User, UserIssuedCredential, set_user_password

#Алфавит без похожих символов: нет 0/O/o, 1/l/I/i. Пароль диктуют вслух и
#переписывают с бумаги — «l или 1?» здесь стоит студенту первого входа.
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_LOWER = "abcdefghjkmnpqrstuvwxyz"
_DIGITS = "23456789"
PASSWORD_LENGTH = 10

#Состояния, которые видит администратор. Строки уходят на клиент как есть.
STATE_NONE = "none"          #стартовый пароль не выдавался
STATE_ISSUED = "issued"      #выдан и ещё действует — его можно посмотреть
STATE_CHANGED = "changed"    #человек сменил пароль сам — показывать нечего


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gen_password(length: int = PASSWORD_LENGTH) -> str:
    """Читаемый случайный пароль: заглавная, строчная и цифра обязательно.

    Спецсимволов нет намеренно: их путают на слух и в разных раскладках («это дефис
    или тире?»), а длина 10 из 55 символов даёт ~58 бит — больше, чем 8 символов с
    полным набором. `secrets`, а не `random`: это ключ от аккаунта."""
    length = max(PASSWORD_LENGTH, int(length or 0))
    alphabet = _UPPER + _LOWER + _DIGITS
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c in _UPPER for c in pw) and any(c in _LOWER for c in pw)
                and any(c in _DIGITS for c in pw)):
            return pw


def _digest(password_hash: str) -> str:
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()


def _row(db, user_id: str):
    return db.get(UserIssuedCredential, user_id)


def issue(db, user: User, plain: str, by: str) -> None:
    """Выдать человеку пароль колледжа: хеш в `users`, шифротекст — сюда.

    ⚠️ Пароль ставится ТОЛЬКО через `models.set_user_password` — её докстринг прямо
    требует, чтобы новое место смены пароля звало её (иначе расходится дата выдачи).
    Коммит — за вызывающим: выдача обычно часть большего действия (выгрузка документа).
    """
    set_user_password(user, plain)
    row = _row(db, user.id)
    if row is None:
        row = UserIssuedCredential(user_id=user.id)
        db.add(row)
    row.secret = gost.encrypt(plain)
    row.hash_digest = _digest(user.password_hash)
    row.issued_at = _now()
    row.issued_by = by or ""
    row.changed_at = ""
    if not gost.enabled():
        #Громко и каждый раз: это не сбой, а режим, о котором администратор обязан знать.
        events.record("warn", "issued_password_plain",
                      "стартовый пароль сохранён без шифрования полей: не задан "
                      "GRADEBOOK_DATA_KEY (база при этом зашифрована целиком)", "", "")


def forget(db, user: User) -> bool:
    """Человек сменил пароль САМ — выданный колледжем больше не показывается никому.

    Возвращает True, если было что стирать. Строку оставляем (см. модель): «сменил
    пароль» и «не выдавался» — разные ответы администратору."""
    row = _row(db, user.id)
    if row is None or not row.secret:
        return False
    row.secret = ""
    row.changed_at = _now()
    return True


def state(db, user: User) -> dict:
    """Что администратор вправе увидеть про стартовый пароль человека.

    🔑 ЗДЕСЬ ЖЕ СВЕРКА: хеш уже не тот, что был при выдаче, — шифротекст стирается
    раньше, чем его успели бы расшифровать. Это и есть граница «придуманный самим
    пароль не виден никому»: путь смены пароля, о котором этот модуль не знает, её не
    обходит. Вызывающий коммитит (стирание — запись).
    """
    row = _row(db, user.id)
    if row is None:
        return {"state": STATE_NONE, "password": "", "issued_at": "", "changed_at": "",
                "has_password": bool(user.password_hash)}
    if row.secret and row.hash_digest != _digest(user.password_hash):
        row.secret = ""
        row.changed_at = _now()
    if not row.secret:
        return {"state": STATE_CHANGED, "password": "", "issued_at": row.issued_at or "",
                "changed_at": row.changed_at or "", "has_password": bool(user.password_hash)}
    plain = gost.decrypt(row.secret)
    if not plain:
        #Не расшифровалось (сменили ключ данных). Показывать пустоту как «пароль» нельзя —
        #администратор продиктует студенту ничего. Честно: выдать заново.
        return {"state": STATE_CHANGED, "password": "", "issued_at": row.issued_at or "",
                "changed_at": row.changed_at or "", "has_password": True,
                "undecryptable": True}
    return {"state": STATE_ISSUED, "password": plain, "issued_at": row.issued_at or "",
            "changed_at": "", "has_password": True}


def reset(db, user: User, by: str) -> str:
    """Новый стартовый пароль (кнопка «Сбросить»). Возвращает его открытым текстом."""
    plain = gen_password()
    issue(db, user, plain, by)
    return plain


def for_rollout(db, user: User, by: str, reset_existing: bool = False) -> tuple:
    """Пароль для строки документа «данные группы». Возвращает (пароль, пометка).

    Правила — ровно четыре, и порядок значим:
      1. стартовый пароль выдан и действует → тот же самый (повторная выгрузка того же
         документа обязана дать те же пароли, иначе распечатанный вчера лист врёт);
      2. человек сменил пароль сам → пароля нет, пометка «сменил пароль». Сбросить его
         молча нельзя: он пользуется своим, и выгрузка выбила бы его из журнала;
      3. пароля нет вовсе → генерируем;
      4. пароль есть, но выдан не через эту таблицу (заведён до 4.0 администратором или
         по заявке) → по умолчанию НЕ трогаем, пометка «задан ранее». Перевыдать можно
         только явным флагом: иначе первая же выгрузка в сентябре выбила бы из журнала
         всех, кто им уже пользуется, — ровно та авария, что уже была с синком (§5.2.2).
    """
    st = state(db, user)
    if st["state"] == STATE_ISSUED:
        return st["password"], ""
    if st["state"] == STATE_CHANGED and not st.get("undecryptable"):
        return "", "changed"
    if not user.password_hash or reset_existing or st.get("undecryptable"):
        return reset(db, user, by), "new"
    return "", "preset"
