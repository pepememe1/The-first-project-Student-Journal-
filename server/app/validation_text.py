"""validation_text.py — человеческий ответ вместо технического 422.

━━ ЗАЧЕМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FastAPI на запрос, не прошедший проверку формы, отвечает 422 и кладёт в `detail` СПИСОК
объектов на английском («Field required», «Input should be a valid integer»). Страница
показывает `detail` человеку как есть — сто двадцать шесть мест в интерфейсе делают
`toast.error(e.response.data.detail || …)`, — и список объектов превращается на экране в
«[object Object]». То есть ровно там, где человек ввёл что-то не то и ему нужна подсказка,
журнал отвечал бессмыслицей.

Чинится здесь, на сервере, а не в ста двадцати шести местах страницы: дверь одна, и
правка доезжает до всех клиентов разом — до сайта, до программы и до приложения на
телефоне, включая уже установленные сборки.

━━ ЧТО ОТДАЁМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`detail` — одна строка по-русски: что не так и что сделать. `errors` — прежний список для
программного разбора, но БЕЗ `input` и `ctx`.

🔒 `input` НЕ ВОЗВРАЩАЕМ. Ответ по умолчанию повторяет присланное значение: пароль,
оказавшийся не в том поле, уехал бы обратно в теле ответа и осел бы в журналах прокси и
в инструментах разработчика на общем компьютере. Человеку его собственный ввод в ответе
не нужен — он у него перед глазами.

⚠️ Имя поля называем ТОЛЬКО когда у него есть подпись, которую человек видит на экране.
Техническое имя (`trust_token`, `device_id`) ему ничего не скажет: такую ошибку он
исправить не может, и честнее посоветовать обновить страницу.
"""

from __future__ import annotations

from typing import Any, Iterable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

#Подписи — как на экране. Поле без подписи считается служебным (см. шапку).
FIELD_LABELS = {
    "login": "Логин",
    "password": "Пароль",
    "new_password": "Новый пароль",
    "old_password": "Текущий пароль",
    "current_password": "Текущий пароль",
    "full_name": "ФИО",
    "surname": "Фамилия",
    "name": "Имя",
    "patronymic": "Отчество",
    "email": "Почта",
    "phone": "Телефон",
    "group": "Группа",
    "group_name": "Группа",
    "subject": "Предмет",
    "title": "Название",
    "description": "Описание",
    "topic": "Тема",
    "date": "Дата",
    "day": "День",
    "year": "Год",
    "semester": "Семестр",
    "room": "Аудитория",
    "value": "Оценка",
    "code": "Код",
    "message": "Сообщение",
    "text": "Текст",
    "body": "Текст",
    "bio": "О себе",
    "birthday": "День рождения",
}

#Сам человек такую ошибку не исправит: страница отправила запрос не той формы.
_NOT_YOUR_FAULT = ("Страница отправила запрос, который сервер не понял. "
                   "Обновите страницу и попробуйте ещё раз.")


def _field_name(loc: Iterable[Any]) -> str:
    """Имя поля — последний текстовый элемент пути (`('body', 'items', 0, 'name')` → name)."""
    for part in reversed(list(loc or ())):
        if isinstance(part, str) and part not in ("body", "query", "path", "header", "cookie"):
            return part
    return ""


def _has_cyrillic(text: str) -> bool:
    return any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text)


def _reason(err: dict) -> str:
    """Причина одним оборотом, без имени поля. Пустая строка — причины для человека нет."""
    kind = str(err.get("type") or "")
    ctx = err.get("ctx") or {}
    if kind == "missing":
        return "его нужно заполнить"
    if kind == "string_too_long":
        limit = ctx.get("max_length")
        return (f"слишком длинное значение (не больше {limit} символов)" if limit
                else "слишком длинное значение")
    if kind == "string_too_short":
        limit = ctx.get("min_length")
        return (f"слишком короткое значение (не меньше {limit} символов)" if limit
                else "слишком короткое значение")
    if kind in ("too_long", "too_short"):
        return "слишком много значений" if kind == "too_long" else "слишком мало значений"
    if kind.startswith(("int_", "float_", "decimal_")) or kind == "finite_number":
        return "здесь должно быть число"
    if kind.startswith("bool_"):
        return "здесь должно быть «да» или «нет»"
    if kind in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        return "число вне допустимых границ"
    if kind.startswith(("date_", "datetime_", "time_")):
        return "дата или время записаны неверно"
    if kind in ("enum", "literal_error"):
        return "такого значения нет среди допустимых"
    if kind == "string_pattern_mismatch":
        return "в значении есть недопустимые символы"
    if kind == "value_error":
        #Свой проверяющий код объясняет причину сам — если он написал её по-русски.
        msg = str(err.get("msg") or "")
        msg = msg.split(",", 1)[1].strip() if msg.lower().startswith("value error,") else msg
        return msg.rstrip(".") if _has_cyrillic(msg) else "значение не подходит"
    return "значение не подходит"


def humanize(errors: list[dict]) -> str:
    """Одна строка для человека: что не так и что сделать."""
    errors = list(errors or [])
    if not errors:
        return _NOT_YOUR_FAULT
    #Сначала ищем ошибку, которую человек способен исправить: поле с подписью в ТЕЛЕ
    #запроса. Параметры адреса и заголовки он не вводил.
    fixable = [e for e in errors
               if (e.get("loc") or ("",))[0] == "body" and _field_name(e.get("loc")) in FIELD_LABELS]
    if not fixable:
        return _NOT_YOUR_FAULT
    first = fixable[0]
    text = f"Проверьте поле «{FIELD_LABELS[_field_name(first.get('loc'))]}»: {_reason(first)}."
    rest = len(fixable) - 1
    if rest > 0:
        text += f" И ещё полей с ошибкой: {rest}."
    return text


def safe_errors(errors: list[dict]) -> list[dict]:
    """Список для программного разбора: где, что за ошибка — без присланных значений."""
    out = []
    for e in errors or []:
        out.append({
            "loc": [p if isinstance(p, (str, int)) else str(p) for p in (e.get("loc") or ())],
            "type": str(e.get("type") or ""),
            "msg": str(e.get("msg") or ""),
        })
    return out


async def _handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    return JSONResponse(status_code=422,
                        content={"detail": humanize(errors), "errors": safe_errors(errors)})


def install(app: FastAPI) -> None:
    """Подключает обработчик. Зовёт `main.py`; тест зовёт её же на пустом приложении."""
    app.add_exception_handler(RequestValidationError, _handler)
