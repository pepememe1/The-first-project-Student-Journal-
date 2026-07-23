"""
terms.py — текущий учебный период (год, семестр) на десктопе.

Десктоп сам по себе семестрами не оперирует (занятия штампует термином сервер при
push), но для итоговых оценок/ведомостей (аттестации) нужен тот же ключ, что и на
сайте. Источник правды — синхронизируемый config (ключи current_year/current_semester,
их выставляет админ); если их нет — дефолт по дате. Формат совпадает с сервером
(server/app/db.default_term + webdata.current_term), чтобы ключи term_grades
десктопа и веба совпадали и данные сливались синком.
"""
from datetime import datetime, timezone


def default_term() -> tuple:
    """Текущий термин по дате: (год «YYYY/YYYY+1», семестр 1|2). ЗЕРКАЛО серверного
    server/app/db.default_term — формула обязана совпадать до символа, иначе ключи
    term_grades десктопа и веба разъедутся.

      • сен–дек  → осень (сем1) Y/Y+1;   • янв → осень (сем1) Y-1/Y;
      • фев–июнь → весна (сем2) Y-1/Y;   • ИЮЛЬ–АВГ → наступающая осень Y/Y+1 (сем1).

    Про лето: июль–август считаем наступающей осенью, а не прошедшей весной — летом
    готовят новый учебный год, и занятия сентября должны сразу попадать в текущий
    термин (иначе журнал по умолчанию показывает пустой прошлый семестр)."""
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month
    if m >= 9:
        return f"{y}/{y + 1}", 1
    if m == 1:
        return f"{y - 1}/{y}", 1
    if m <= 6:
        return f"{y - 1}/{y}", 2
    return f"{y}/{y + 1}", 1        #июль–август: наступающая осень


def current_term() -> tuple:
    """Текущий учебный термин (год, семестр) из синкнутого config, иначе — по дате.
    Так итоговая оценка, выставленная на ПК, попадёт в тот же семестр, что и на сайте."""
    try:
        from data_store import get_store
        cfg = get_store()._config() or {}
    except Exception:
        cfg = {}
    y = (cfg.get("current_year") or "").strip()
    s = cfg.get("current_semester")
    if y and s:
        try:
            return y, int(s)
        except (TypeError, ValueError):
            pass
    return default_term()


def semester_label(semester) -> str:
    """Человекочитаемое название семестра для заголовков ведомости."""
    try:
        s = int(semester)
    except (TypeError, ValueError):
        return str(semester)
    return "осенний" if s == 1 else ("весенний" if s == 2 else str(s))
