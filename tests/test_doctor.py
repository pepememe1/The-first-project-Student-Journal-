"""
test_doctor.py — самопроверка установки (3.7.6).

Она нужна ровно тогда, когда всё остальное сломано, поэтому проверяем два свойства:
она НЕ падает, что бы ни отсутствовало, и она ПОДКЛЮЧЕНА к точке входа. Второе важнее
первого: «обещание без вызывающего» — самый частый класс дефекта в этом проекте, а
проверка, которую нельзя запустить, ничем не отличается от её отсутствия.
"""
from pathlib import Path

import doctor


def test_report_is_produced_and_names_the_essentials():
    out = doctor.report()
    for word in ("ПАКЕТЫ", "НАСТРОЙКИ", "СЕТЬ", "httpx"):
        assert word in out, f"в отчёте нет раздела/пункта «{word}»"


def test_report_survives_a_broken_environment(monkeypatch):
    """Сломанные настройки не должны ронять проверку: она для сломанных машин и есть."""
    import data.app_settings as st

    def boom(*a, **k):
        raise RuntimeError("база недоступна")

    monkeypatch.setattr(st, "get_api_url", boom)
    monkeypatch.setattr(st, "get_saved_session", boom)
    out = doctor.report()
    assert "НАСТРОЙКИ" in out            #отчёт всё равно собрался
    assert "RuntimeError" in out         #и честно назвал, что именно сломано


def test_doctor_is_reachable_from_the_entry_point():
    """СТОРОЖ ВЫЗОВА: `--doctor` обязан быть разобран в main.py, иначе проверку просто
    нечем запустить у того, кому она нужна."""
    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "--doctor" in src, "флаг не разбирается в точке входа"
    assert "doctor.main()" in src, "флаг разбирается, но проверка не вызывается"
