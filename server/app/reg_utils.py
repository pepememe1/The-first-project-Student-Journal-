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
