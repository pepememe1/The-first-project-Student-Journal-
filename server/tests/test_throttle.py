"""
test_throttle.py — Определение IP клиента для анти-брутфорса за обратным прокси.

Регрессия безопасности: раньше client_ip брал ПЕРВЫЙ элемент X-Forwarded-For, который
задаёт сам клиент. Атакующий слал случайный XFF на каждой попытке входа → счётчик
(IP, логин) не срабатывал и серверная защита от перебора пароля обходилась. Теперь
доверяем X-Real-IP (его ставит Caddy из проверенного TCP-пира), а из XFF берём
ПОСЛЕДНИЙ хоп (дописанный прокси), а не подделываемый первый.
"""
from app import throttle


class _Req:
    """Минимальный дублёр Request: важны только .headers.get() и .client.host."""
    def __init__(self, headers=None, host=None):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})() if host else None


def test_prefers_x_real_ip():
    #X-Real-IP выставлен прокси — берём его, игнорируя подделанный клиентом XFF.
    r = _Req(headers={"x-real-ip": "203.0.113.7",
                      "x-forwarded-for": "9.9.9.9, 203.0.113.7"}, host="127.0.0.1")
    assert throttle.client_ip(r) == "203.0.113.7"


def test_xff_takes_last_hop_not_spoofed_first():
    #Без X-Real-IP: реальный клиент — ПОСЛЕДНИЙ хоп (его дописал Caddy), а не
    #подделанный клиентом первый (9.9.9.9).
    r = _Req(headers={"x-forwarded-for": "9.9.9.9, 8.8.8.8, 203.0.113.7"}, host="127.0.0.1")
    assert throttle.client_ip(r) == "203.0.113.7"


def test_spoofed_first_entry_does_not_evade_throttle():
    #Ключевая регрессия: два запроса с РАЗНЫМ подделанным первым XFF, но одним реальным
    #последним хопом → один и тот же ключ блокировки (перебор не «размазывается»).
    r1 = _Req(headers={"x-forwarded-for": "1.1.1.1, 203.0.113.7"}, host="127.0.0.1")
    r2 = _Req(headers={"x-forwarded-for": "2.2.2.2, 203.0.113.7"}, host="127.0.0.1")
    assert throttle.client_ip(r1) == throttle.client_ip(r2) == "203.0.113.7"


def test_direct_connection_fallback():
    #Совсем без прокси (dev): берём прямой адрес соединения.
    r = _Req(headers={}, host="192.168.1.50")
    assert throttle.client_ip(r) == "192.168.1.50"


def test_single_xff_value():
    r = _Req(headers={"x-forwarded-for": "203.0.113.7"}, host="127.0.0.1")
    assert throttle.client_ip(r) == "203.0.113.7"
