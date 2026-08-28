"""
reg_utils.py — помощники самостоятельной регистрации студентов.

  • генерация пароля (8 симв, ≥1 заглавная, ≥1 спецсимвол — по требованию);
  • валидация телефона (+7 и 10 цифр) и e-mail (только разрешённые домены);
  • resolve_group — сопоставление введённой студентом группы с реальной. В расписании
    встречаются «сдвоенные» группы одной строкой (напр. «К104/2,105.0»): если студент
    ввёл просто «К104/2», регистрация разрешается, а привязывается он к «К104/2,105.0».
"""
import re
import secrets
import string

#Разрешённые домены почты (по требованию заказчика). .com и прочие — нельзя.
ALLOWED_EMAIL_DOMAINS = ("yandex.ru", "mail.ru", "esstu.ru")
_SPECIALS = "!@#$%^&*"


def gen_password(length: int = 8) -> str:
    """Пароль ≥8 символов: минимум 1 заглавная, 1 строчная, 1 цифра, 1 спецсимвол."""
    length = max(8, length)
    alphabet = string.ascii_letters + string.digits + _SPECIALS
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pw) and any(c.islower() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in _SPECIALS for c in pw)):
            return pw


def valid_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if not re.match(r"^[a-z0-9][a-z0-9._%+-]*@[a-z0-9.-]+\.[a-z]{2,}$", email):
        return False
    domain = email.rsplit("@", 1)[-1]
    return domain in ALLOWED_EMAIL_DOMAINS


def normalize_phone(phone: str) -> str:
    """Приводит к виду +7XXXXXXXXXX (только цифры), или '' если номер некорректен.
    Принимает 8XXXXXXXXXX, +7XXXXXXXXXX, 7XXXXXXXXXX и с любыми разделителями."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:]
    if len(digits) == 10:
        return "+7" + digits
    return ""


def resolve_group(group_input: str, existing_names) -> str:
    """Возвращает РЕАЛЬНОЕ имя группы для введённого студентом, либо '' если такой нет.
    Логика: точное совпадение → совпадение с любым сегментом «сдвоенной» группы
    (строка вида «К104/2,105.0» разбивается по запятой)."""
    g = (group_input or "").strip()
    if not g:
        return ""
    names = list(existing_names or [])
    if g in names:
        return g
    for n in names:
        segments = [p.strip() for p in n.split(",")]
        if g in segments:                    #«К104/2» ∈ [«К104/2», «105.0»] → «К104/2,105.0»
            return n
    #мягко: без учёта регистра/пробелов
    gl = g.lower()
    for n in names:
        if any(p.strip().lower() == gl for p in n.split(",")):
            return n
    return ""


def valid_full_name(full_name: str) -> bool:
    parts = (full_name or "").strip().split()
    return len(parts) >= 2 and all(len(p) >= 2 for p in parts[:2])


def gen_invite_token() -> str:
    """Токен приглашения в группу. 32 символа urlsafe — это и есть право на регистрацию.

    ⚠️ `secrets`, а не `uuid4`: uuid4 в CPython тоже берёт криптостойкий источник, но это
    не его назначенная роль, и следующий читатель не обязан это знать. Секрет должен
    выглядеть секретом в коде.
    """
    return secrets.token_urlsafe(24)


def create_student_account(db, email: str, full_name: str, group: str, now_iso: str):
    """Завести студента по подтверждённым данным. Возвращает (row, сгенерированный пароль).

    🔑 ЕДИНСТВЕННЫЙ путь создания студента «снаружи»: им пользуются И одобрение заявки
    администратором (`/web/admin/registrations/approve`), И регистрация по приглашению
    куратора (`/auth/register-invite`). Второй копии этой логики быть не должно — в ней
    сидят формат id (`stud:{email}`, тот же, что в синке), разбор ФИО на фамилию/имя/
    отчество и серверная метка времени. Разъехавшись, две копии дали бы студентов,
    которых десктоп считает разными людьми.

    ⚠️ Проверку «такой почты ещё нет» делает ВЫЗЫВАЮЩИЙ: у заявки и у приглашения на
    дубликат разные ответы (одну надо пометить отклонённой, второй — просто отказать).
    """
    from .models import User, set_user_password
    pw = gen_password()
    #name = «Имя Отчество» (parts[1:]) — исторический КЛЮЧ, не менять: по нему ключуются
    #оценки и ростер. Отчество дополнительно кладём в своё поле.
    parts = (full_name or "").split()
    sid = f"stud:{email}"
    row = db.get(User, sid)
    if row is None:
        row = User(id=sid)
        db.add(row)
    row.role = "student"
    row.login = email
    set_user_password(row, pw)
    row.full_name = full_name
    row.surname = parts[0] if parts else ""
    row.name = " ".join(parts[1:]) if len(parts) > 1 else ""
    row.patronymic = " ".join(parts[2:]) if len(parts) > 2 else ""
    row.group_name = group
    row.subjects = []
    row.group_assignments = {}
    row.updated_at = now_iso
    row.deleted = False
    return row, pw


def invite_blocked_reason(inv, now_iso: str) -> str:
    """'' — приглашение действует; иначе причина отказа человеческим языком.

    🔑 Живёт ЗДЕСЬ, а не рядом с ручкой выдачи, потому что смотрят на него ДВЕ стороны:
    куратор в своём списке («ссылка ещё жива?») и публичная регистрация («пустить ли по
    ней?»). Две копии этой проверки разъехались бы молча и в худшую сторону: ссылка
    зелёная в списке куратора, а студенту отвечает отказом — и объяснить это студенту
    куратор не сможет.

    ⚠️ Три ограничителя проверяются ВМЕСТЕ, и ни один не лишний: срок (вечная ссылка
    переживёт выпуск и смену куратора), число мест (утёкшая ссылка не должна заводить
    сто аккаунтов) и отзыв (единственный способ закрыть утёкшую ссылку немедленно).
    """
    if inv is None:
        return "Приглашение не найдено"
    if getattr(inv, "revoked", False):
        return "Приглашение отозвано"
    if inv.expires_at and now_iso > inv.expires_at:
        return "Срок действия приглашения истёк"
    if inv.max_uses and int(inv.uses or 0) >= int(inv.max_uses):
        return "Приглашение уже использовано максимальное число раз"
    return ""
