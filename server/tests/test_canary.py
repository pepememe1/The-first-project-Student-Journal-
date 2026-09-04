"""
test_canary.py — ПРИМАНКИ: пути, к которым не обращается никто законный (04.09.2026).

Идея Ярослава по мотивам «Мистер Робот»; разбор и требования — `docs/PLAN-HONEYPOT.md`.
Приманка — ДЕТЕКТОР, а не щит: она не мешает попасть внутрь, она делает попытку заметной
с первой секунды, потому что шума в ней нет по построению.

Что здесь держится (и что покраснеет, если правку откатить):
  • обращение к приманке банит источник и оставляет след;
  • 🔴 ОБЫЧНЫЙ путь бана НЕ даёт — иначе сторож ловит своих, и журнал перестаёт
    открываться колледжу;
  • 🔴 доверенный адрес не банится НИКОГДА, даже на приманке (колледж за одним NAT:
    один студент со сканером отрезал бы всё здание);
  • honeytoken не пускает внутрь ни при каких условиях и отвечает КАК обычная неудача;
  • ответ уходит мгновенно — в middleware нет ни сна, ни похода в сеть (одно ядро,
    один процесс: задержка там останавливает журнал всему колледжу).
"""
import time

from app import canary, throttle
from conftest import make_admin


def _reset():
    throttle.reset()


# ── приманки ────────────────────────────────────────────────────────────────────────

def test_canary_path_bans_the_source(client, monkeypatch):
    """Обращение к приманке банит адрес и отдаёт плашку, а не 404."""
    _reset()
    #Клиент тестов приходит как «testclient» — он в доверенных, иначе забанил бы себя.
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)

    r = client.get("/.env")
    assert r.status_code == 200, r.text
    assert "Loading" in r.text and "<html" in r.text.lower()

    #Следующий запрос — уже отказ, независимо от пути.
    assert client.get("/health").status_code == 429


def test_ordinary_paths_never_ban(client, monkeypatch):
    """🔴 ОБРАТНЫЙ ХОД: обычные пути бана не дают.

    Уберёшь список и начнёшь банить по догадке — этот тест краснеет. Он и есть граница
    между «поймали сканер» и «отрезали колледж».
    """
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)

    for path in ("/health", "/robots.txt", "/offer.html", "/web/student/overview"):
        client.get(path)
        assert throttle.seconds_until_unbanned("testclient") == 0, path


def test_trusted_ip_is_never_banned(client, monkeypatch):
    """🔴 Доверенный адрес не банится даже на приманке.

    Без белого списка фичу включать нельзя вовсе: колледж за одним NAT, и один сканер
    с чьего-то ноутбука закрыл бы журнал всему зданию.
    """
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: True)

    assert client.get("/.env").status_code == 200
    assert client.get("/health").status_code != 429, "доверенный адрес забанен"


def test_trust_list_comes_from_the_environment(monkeypatch):
    """Список доверенных читается из окружения — правят его в аварийной ситуации."""
    _reset()
    monkeypatch.setenv("GRADEBOOK_TRUST_IPS", "10.0.0.7, 10.0.0.8")
    assert throttle.is_trusted("10.0.0.7") and throttle.is_trusted("10.0.0.8")
    assert not throttle.is_trusted("10.0.0.9")


def test_loopback_is_trusted_by_default():
    """Петля своя всегда: иначе локальный сервер программы забанил бы сам себя."""
    _reset()
    assert throttle.is_trusted("127.0.0.1") and throttle.is_trusted("::1")


def test_ban_expires(monkeypatch):
    """Бан срочный, а не вечный: вечный оборачивается разблокировкой руками."""
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    assert throttle.ban_ip("203.0.113.5", 1) is True
    assert throttle.seconds_until_unbanned("203.0.113.5") > 0
    time.sleep(1.1)
    assert throttle.seconds_until_unbanned("203.0.113.5") == 0


def test_directory_prefixes_are_covered(monkeypatch):
    """В деревья (`/.git/…`) лезут целиком — ловим по префиксу, а не поштучно."""
    assert canary.is_canary("/.git/config") and canary.is_canary("/.aws/credentials")
    assert canary.is_canary("/wp-content/uploads/x.php")


def test_legitimate_paths_are_not_in_the_list():
    """Сторож на состав списка: законный путь в приманках — это бан живого человека."""
    for path in ("/", "/health", "/robots.txt", "/sitemap.xml", "/offer.html",
                 "/privacy.html", "/terms.html", "/favicon.svg",
                 "/web/student/overview", "/auth/login", "/downloads/GradeBookAI.exe"):
        assert not canary.is_canary(path), path


# ── honeytoken ──────────────────────────────────────────────────────────────────────

def test_honeytoken_never_lets_anyone_in(client, monkeypatch):
    """Вход под приманкой невозможен и выглядит как обычная неудача.

    ⚠️ Ответ обязан совпадать с обычным отказом: иное сообщение объяснило бы
    атакующему, какие именно данные у него помечены.
    """
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)

    r = client.post("/auth/login", json={"login": canary.HONEY_LOGIN, "password": "x"})
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == "Неверный логин или пароль"
    assert throttle.seconds_until_unbanned("testclient") > 0, "утечка не забанена"


def test_honeytoken_is_not_a_row_in_users(client):
    """🔴 Приманки НЕТ в таблице пользователей — и не должно быть.

    Строка-приманка попала бы в списки, выгрузки, средние баллы и отчёт куратора, и её
    пришлось бы не забыть исключить в двух десятках выборок. Ровно тот класс дефекта,
    из-за которого заявка в беседу сделана отдельной таблицей.
    """
    _reset()
    admin = make_admin(client)
    logins = {s["login"] for s in
              client.get("/web/admin/students", headers=admin).json()["students"]}
    logins |= {t["login"] for t in
               client.get("/web/admin/teachers", headers=admin).json()["teachers"]}
    assert canary.HONEY_LOGIN not in logins


# ── свойство: приманка не тормозит сервер ───────────────────────────────────────────

def test_decoy_answers_instantly(client, monkeypatch):
    """🔴 НИКАКОГО TARPIT. Одно ядро и один процесс: задержка в middleware
    останавливает журнал всему колледжу. «Загрузку» рисует CSS у клиента."""
    _reset()
    monkeypatch.setattr(throttle, "is_trusted", lambda ip: False)
    started = time.monotonic()
    client.get("/.env")
    assert time.monotonic() - started < 1.0, "приманка держит соединение — это tarpit"


def test_canary_module_has_no_sleep_or_network():
    """Свойство по тексту модуля: сна и сети в приманке нет и быть не может.

    Тот же приём, что у `test_event_loop_not_blocked.py`. Докстринги вырезаем — они
    обязаны ОБЪЯСНЯТЬ запрет, и упоминание слова в объяснении не нарушение.
    """
    import ast
    import inspect
    src = inspect.getsource(canary)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            node.value.value = ""          # docstring → пусто
    body = ast.unparse(tree)
    for bad in ("sleep", "requests.", "httpx.", "urlopen"):
        assert bad not in body, f"в приманке появился {bad} — это tarpit"
