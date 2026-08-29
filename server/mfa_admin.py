#!/usr/bin/env python3
"""mfa_admin.py — аварийный сброс второго фактора. Запускается НА СЕРВЕРЕ.

━━ ЗАЧЕМ НУЖЕН ИМЕННО ТАКОЙ ИНСТРУМЕНТ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Второй фактор обязателен для администратора, и это правильно ровно до того дня,
когда единственный администратор колледжа теряет телефон, а коды восстановления
лежат в ящике стола, который заперт. Без выхода из этой ситуации журнал остаётся
без управления, и «починка» сводится к правке базы руками — то есть к тому, от
чего мы и уходили.

Поэтому выход есть, и он устроен так, чтобы им нельзя было воспользоваться
удалённо:

  🔒 РУЧКИ В API НЕТ И НЕ БУДЕТ. Сброс делается только с самой машины сервера,
     под учётной записью, у которой уже есть доступ к базе. Иначе «аварийный
     сброс» — это просто обход второго фактора по HTTP, и вся конструкция теряет
     смысл. Та же граница, что у раздела «Сервер» (§16): защищает не проверка
     роли, а отсутствие кода на боевом сервере.

  🔒 СЛЕД ОСТАЁТСЯ ВСЕГДА. Сброс пишется в журнал аудита с именем того, кто его
     выполнил, и причиной. Тихий аварийный вход — подарок нарушителю: именно он
     и будет им пользоваться, а мы не узнаем.

Запуск (в venv сервера, из каталога развёртывания):
    python mfa_admin.py --list
    python mfa_admin.py --reset admin --by "Ярослав" --reason "утерян телефон"
"""

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import audit                    # noqa: E402
from app.db import SessionLocal          # noqa: E402
from app.models import User, UserMFA     # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cmd_list(db) -> int:
    rows = db.query(UserMFA).all()
    by_id = {u.id: u for u in db.query(User).all()}
    if not rows:
        print("Второй фактор не настроен ни у кого.")
        return 0
    print(f"{'логин':20} {'роль':10} {'включён':21} {'кодов осталось'}")
    for r in rows:
        u = by_id.get(r.user_id)
        left = sum(1 for h in (r.recovery_hashes or []) if h)
        print(f"{(u.login if u else r.user_id):20} {(u.role if u else '?'):10} "
              f"{(r.confirmed_at or 'не подтверждён'):21} {left}")
    return 0


def cmd_reset(db, login: str, by: str, reason: str) -> int:
    user = db.query(User).filter(User.login == login).first()
    if not user:
        print(f"Нет пользователя с логином {login!r}", file=sys.stderr)
        return 1
    row = db.query(UserMFA).filter(UserMFA.user_id == user.id).first()
    if not row:
        print(f"У {login} второй фактор и так не настроен — сбрасывать нечего.")
        return 0

    # ⚠️ Строку УДАЛЯЕМ, а не «выключаем флагом». Выключенный флаг оставил бы в базе
    # старый секрет, и тот, у кого он есть, продолжил бы генерировать коды после того,
    # как мы сочли фактор сброшенным.
    db.delete(row)
    audit.log(db, None, actor=by or "(не указан)", role="admin",
              action="mfa.reset_emergency", target=login, level="warn",
              detail=f"аварийный сброс второго фактора на сервере; причина: {reason}")
    db.commit()
    print(f"Второй фактор для {login} сброшен {_now()} UTC.")
    print("⚠️ Человек войдёт по одному паролю. Настроить фактор заново — ОБЯЗАТЕЛЬНО:")
    print("   на боевом сервере администратор без него не получит прав.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="у кого настроен второй фактор")
    ap.add_argument("--reset", metavar="ЛОГИН", help="сбросить второй фактор")
    ap.add_argument("--by", default="", help="кто выполняет сброс (идёт в журнал аудита)")
    ap.add_argument("--reason", default="", help="причина (идёт в журнал аудита)")
    args = ap.parse_args()

    if not args.list and not args.reset:
        ap.print_help()
        return 2

    # Причину требуем ЯВНО. Не формальность: журнал аудита без причины отвечает на
    # вопрос «что произошло», но не на «почему», а разбирать инцидент придётся именно
    # по второму.
    if args.reset and not (args.by and args.reason):
        print("Для сброса обязательны --by и --reason: это событие безопасности, "
              "и оно должно быть объяснимо через полгода.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        if args.list:
            return cmd_list(db)
        return cmd_reset(db, args.reset, args.by, args.reason)


if __name__ == "__main__":
    sys.exit(main())
