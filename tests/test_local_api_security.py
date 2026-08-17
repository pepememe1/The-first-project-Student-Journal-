"""Границы локального сервера программы (адверсариальный разбор 17.08.2026).

Локальный сервер — это тот же пакет `server/app`, поднятый на 127.0.0.1 внутри десктопа.
Он выглядит безобидно («слушаем только петлю»), но у него есть свойство, которого нет ни
у сайта, ни у мобилки: `install_remote_proxy` подставляет к запросу БОЕВОЙ токен вошедшего
человека. Значит любой, кто сумел получить ЛОКАЛЬНЫЙ токен, получает доступ не к копии
данных, а к настоящему аккаунту на esstu-gradebook.ru — переписка, уведомления, профиль,
а у администратора ещё и раздел «Сервер».

Отсюда два свойства, которые здесь и закрепляются:
  1) токены локального сервера подписаны ключом ЭТОГО устройства, а не общеизвестным
     `DEV_JWT_SECRET` из исходников (он лежит открытым литералом в каждом раздаваемом .exe);
  2) страница из чужого домена, открытая у человека в браузере, не разговаривает с
     локальным сервером — а она могла: `server/app` вешает CORS `allow_origins=["*"]`,
     потому что список origin'ов задаётся переменной окружения, которой у десктопа нет.
     В связке с `GET /desktop/bootstrap` (он не требует авторизации ВООБЩЕ и отдаёт свежий
     локальный токен прямо в теле страницы) это давало посторонннему сайту полный доступ
     к боевому аккаунту — достаточно было найти эфемерный порт перебором.
"""
import os
import urllib.error
import urllib.request

import pytest

from desktop import local_api


def test_local_server_does_not_sign_with_the_public_dev_secret(monkeypatch, tmp_path):
    """Ключ подписи — свой на устройство, а не литерал из исходников."""
    monkeypatch.setenv("GRADEBOOK_APP_DIR", str(tmp_path))
    monkeypatch.delenv("GRADEBOOK_JWT_SECRET", raising=False)
    monkeypatch.setattr(local_api, "_jwt_cache", None)

    secret = local_api._local_jwt_secret()

    assert secret and secret != "dev-secret-change-me"
    assert len(secret) >= 32, "короткий ключ подписи — половина защиты"


def test_the_key_survives_a_restart(monkeypatch, tmp_path):
    """ОБРАТНЫЙ ХОД: ключ не «случайный каждый раз».

    Без этой проверки «починкой» выглядел бы и вариант со свежим ключом на каждый вызов —
    первый тест остался бы зелёным, а человек получал бы разлогин при каждом обращении к
    локальному серверу. Ключ обязан быть постоянным для устройства и лежать под DPAPI."""
    monkeypatch.setenv("GRADEBOOK_APP_DIR", str(tmp_path))
    monkeypatch.setattr(local_api, "_jwt_cache", None)
    first = local_api._local_jwt_secret()
    monkeypatch.setattr(local_api, "_jwt_cache", None)      #как будто программу перезапустили
    second = local_api._local_jwt_secret()

    assert first == second, "ключ пересоздаётся при каждом обращении — сессия не переживёт " \
                            "перезапуск программы"
    import app_paths
    assert os.path.exists(app_paths.data_file("local_app.jwt")), \
        "ключ обязан лежать файлом (под DPAPI), иначе он не переживёт перезапуск"


def test_prepare_env_puts_the_key_into_the_environment(monkeypatch, tmp_path):
    """Ключ обязан попасть в окружение ДО импорта `app.config` — тот читает переменную
    один раз, в момент импорта, и опоздавшее значение уже ни на что не влияет."""
    monkeypatch.setenv("GRADEBOOK_APP_DIR", str(tmp_path))
    monkeypatch.delenv("GRADEBOOK_JWT_SECRET", raising=False)
    monkeypatch.setattr(local_api, "_jwt_cache", None)
    try:
        local_api.prepare_env()
    except Exception as e:                     # noqa: BLE001
        pytest.skip(f"серверный пакет недоступен в этом окружении: {e}")

    assert os.environ.get("GRADEBOOK_JWT_SECRET", "") not in ("", "dev-secret-change-me")


# ── Заслонка чужого origin ────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def api():
    import tempfile
    tmp_db = os.path.join(tempfile.mkdtemp(), "local_app_sec.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp_db}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен в этом окружении: {srv.error}")
    yield srv
    srv.stop()


def _status(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_a_page_from_another_site_is_turned_away(api):
    """Сторонний origin получает 403 ещё до того, как запрос куда-либо уйдёт."""
    assert _status(api.url("/health"), {"Origin": "https://evil.example"}) == 403


def test_the_bootstrap_page_does_not_hand_the_session_to_a_foreign_page(api):
    """Главное следствие: страница-передатчик отдаёт токен только своим.

    Проверяем ИМЕННО этот маршрут, а не только `/health`: он не требует авторизации по
    построению (иначе оболочка не смогла бы передать сессию) и потому был самой короткой
    дорогой к боевому аккаунту."""
    assert _status(api.url("/desktop/bootstrap"), {"Origin": "https://evil.example"}) == 403


def test_own_page_and_desktop_calls_still_work(api):
    """ОБРАТНЫЙ ХОД, и он обязателен: заслонка, отвергающая ВСЁ, прошла бы оба теста выше
    и при этом не дала бы программе открыться вовсе — окно грузит SPA с этого же адреса.

    ⚠️ Этот тест уже окупился дважды. Первая версия заслонки сверяла порт с тем сервером,
    который её ставил, и падала здесь; вторая падала только в ПОЛНОМ прогоне, потому что
    `_load_app()` отдаёт МОДУЛЬНЫЙ объект приложения — второй локальный сервер в том же
    процессе вешал вторую заслонку, а первая, с уже недействительным портом, продолжала
    отвергать. В продукте это означало бы мёртвое окно после цикла «стоп → старт»."""
    assert _status(api.url("/health")) == 200, "запрос без Origin (оболочка окна) обязан пройти"
    assert _status(api.url("/health"), {"Origin": api.url("").rstrip("/")}) == 200, \
        "запрос со СВОЕГО origin (сама SPA) обязан пройти"


def test_a_lookalike_host_is_not_mistaken_for_the_loopback(api):
    """Похожий на петлю чужой домен — всё равно чужой.

    Проверка узкая намеренно: раз «свой» теперь определяется без сверки порта, единственное,
    что отделяет своего от чужого, — разбор ХОСТА. Поиск подстроки «127.0.0.1» пропустил бы
    оба этих адреса, и в этом проекте на такой ошибке уже обжигался сторож вёрстки."""
    assert _status(api.url("/health"), {"Origin": "https://127.0.0.1.evil.example"}) == 403
    assert _status(api.url("/health"), {"Origin": "https://evil.example/#127.0.0.1"}) == 403
