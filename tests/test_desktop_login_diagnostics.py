"""
test_desktop_login_diagnostics.py — почему именно не пустило в программу (3.7.6).

Живой случай: тестировщик (Матвей) склонировал репозиторий и не смог войти вообще.
Разбираться было НЕЧЕМ: мост входа отвечает одинаковым «Неверный логин или пароль,
либо нет связи» и на неверный пароль, и на любой сбой по дороге к серверу — от
отсутствующего пакета до TLS. Человек читает это как «пароль не подходит» и идёт
менять пароль, хотя проблема в другом месте.

Слипание сделано НАМЕРЕННО ради одного случая — чтобы не подсказывать подбирающему,
что «такой логин есть, но пароль не тот». Этот довод верен только для ответа СЕРВЕРА
(401). Когда до сервера вообще не дошли, скрывать нечего: там нет ни логина, ни
пароля — есть сеть. Тот же урок уже записан в §16 CLAUDE.md про раздел «Сервер»:
«нет связи» при живом интернете отправляет человека проверять провайдера вместо входа.
"""
from desktop import local_api


def test_unreachable_server_is_not_called_a_wrong_password(monkeypatch):
    """🔥 Главное: до сервера не дошли — так и говорим, и это ДРУГОЙ код ответа."""
    monkeypatch.setattr(local_api, "_try_local_login", lambda *a, **k: None)
    monkeypatch.setattr(local_api, "switch_user_db", lambda *a, **k: False)
    monkeypatch.setattr(local_api, "_try_remote_login",
                        lambda *a, **k: (None, "offline: имя сервера не разрешается"))

    status, detail = local_api.login_failure_response(None, "offline: имя сервера не разрешается")
    assert status == 503, "недоступный сервер отвечает как неверный пароль"
    assert "связ" in detail.lower() or "сервер" in detail.lower()


def test_server_said_no_stays_ambiguous():
    """Обратная сторона: когда ответил САМ сервер, ответ остаётся неразличимым —
    «такого логина нет» и «пароль не тот» обязаны выглядеть одинаково."""
    status, detail = local_api.login_failure_response(None, "unauthorized")
    assert status == 401
    assert "логин" in detail.lower() and "парол" in detail.lower()
    assert "нет" not in detail.lower().split("парол")[0], "не подсказываем, что именно не так"


def test_reason_reaches_the_log(monkeypatch, caplog):
    """Причина обязана попасть в лог: на чужой машине это единственный след, по
    которому вообще можно разобраться, — там нет ни отладчика, ни нас."""
    import logging

    with caplog.at_level(logging.WARNING):
        local_api.login_failure_response(None, "offline: SSL: CERTIFICATE_VERIFY_FAILED")
    assert any("CERTIFICATE_VERIFY_FAILED" in r.message for r in caplog.records), \
        "причина отказа не записана в лог"
