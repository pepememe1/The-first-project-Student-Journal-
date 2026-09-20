"""
test_shared_broadcast_is_wired.py — у межпроцессных сигналов есть и писатель, и читатель
(20.09.2026).

━━ ЗАЧЕМ ЭТОТ СТОРОЖ ━━
`tests/test_ws_shared_broadcast.py` задаёт КОНТРАКТ (что публикуется и как читается), но
он зелёный и тогда, когда потребителя никто не запускает: в нём цикл вызывается руками.
А это наш самый частый класс дефекта — «обещание без вызывающего»: сигналы копятся в
общем потоке, второй воркер их не видит, и переход на несколько процессов МОЛЧА ухудшает
мессенджер (сокет считается живым, и опрос именно поэтому разрежен до 30 с).

⚠️ Проверяется ВЫЗОВ, а не поведение: поведение уже покрыто контрактом рядом.

⚠️ И вторая половина — цена. Потребитель обязан запускаться ТОЛЬКО при поднятом общем
состоянии: без `GRADEBOOK_REDIS_URL` фоновый цикл на одноядерном сервере это чистый
расход ядра, а поведение продукта обязано остаться буквально прежним.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `create_task(..._consume_shared())` из `lifespan` —
краснеет первый тест; снять условие `available()` — краснеет второй.
"""
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _lifespan_source() -> str:
    src = (APP / "main.py").read_text(encoding="utf-8")
    start = src.index("async def lifespan")
    end = src.index("\n_PROD", start)
    #Комментарии вырезаем: они объясняют, ЗАЧЕМ заведён потребитель, и разбор, считающий
    #пояснение кодом, зеленел бы на файле, где вызова уже нет.
    return re.sub(r"(?m)^\s*#.*$", "", src[start:end])


def test_the_consumer_is_actually_started():
    body = _lifespan_source()
    assert "_consume_shared()" in body, (
        "публикуем сигналы в общий поток и никто их не читает — второй воркер не узнает "
        "о чужих сообщениях, а опрос уже разрежен в расчёте на живой сокет")
    assert "create_task" in body, "потребитель не уходит в фон — он заблокирует запуск"


def test_the_consumer_starts_only_when_shared_state_is_up():
    body = _lifespan_source()
    at = body.index("_consume_shared()")
    head = body[:at]
    assert "available()" in head, (
        "фоновый цикл заводится и без общего состояния — на одноядерном бою это расход "
        "единственного ядра там, где процесс всё равно один")


def test_the_signal_carries_no_personal_data():
    """Через общий поток ПДн не едут: Redis обработку персональных данных мы не поручали."""
    src = (APP / "routers" / "messenger" / "_common.py").read_text(encoding="utf-8")
    at = src.index("def _broadcast(")
    body = src[at:at + 2000]
    published = body[body.index("stream_append"):body.index("maxlen=500")]
    for forbidden in ("body", "text", "full_name", "email", "login", "sender"):
        assert f'"{forbidden}"' not in published, (
            f"в межпроцессный сигнал попало поле {forbidden!r} — это уже не сигнал, "
            f"а пересылка содержимого в чужое хранилище")
