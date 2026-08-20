"""
test_desktop_first_login.py — ПЕРВЫЙ вход на чистой машине (3.7.7).

Живой случай (Матвей, тестировщик): склонировал репозиторий, ввёл верные логин и
пароль — «аккаунт на секунду вылезает, потом опять главный вход и та самая ошибка».
На наших машинах всё работало.

━━ ЦЕПОЧКА, КОТОРУЮ ДЕРЖАТ ЭТИ ТЕСТЫ ━━
1. Мост входа не нашёл человека в локальной копии (её на чистой машине нет вовсе) и
   пошёл на боевой сервер. Туда он стучится с заголовком `X-Client: web`, поэтому
   барьер устройства ему не мешает — вход ПРОХОДИТ.
2. Дальше нужно наполнить локальную копию (`local_mirror`). А вот зеркало ходит уже
   НАСТОЯЩИМ десктопным клиентом (`sync/sync_client.py`), без `X-Client`, — и для него
   барьер устройства работает в полную силу: неодобренный ПК получает 403 на `/sync/*`
   и даже на собственный `/auth/login`. Копия остаётся пустой.
3. `issue_local_session` выписывает токен НЕ СМОТРЯ на то, есть ли человек в копии:
   она падает только на исключении. Поэтому страховка `if not access: return remote`
   в мосте не срабатывала НИКОГДА — ровно тот класс дефекта, что записан в шапке
   CLAUDE.md как «обещание без вызывающего».
4. SPA получает валидный по подписи токен на несуществующего пользователя. Первый же
   запрос кабинета → 401 «Пользователь не найден» → интерсептор пробует refresh →
   снова 401 → `clearTokens()` и возврат на форму входа. Это и есть «мелькнул и
   выкинуло»: между пунктами 3 и 4 проходит меньше секунды.

━━ ПОЧЕМУ ЭТО НЕ ЧАСТНЫЙ СЛУЧАЙ ОДНОГО ТЕСТИРОВЩИКА ━━
Барьер устройства для десктопа — инвариант (§4.11), ослаблять его нельзя. Значит через
эту дверь пройдёт КАЖДЫЙ новый компьютер преподавателя при развёртывании в колледже.
При этом путь «запросить подтверждение и ввести код» на десктопе не существовал: методы
`SyncClient.connect_request/connect_status/connect_verify` были написаны и не имели НИ
ОДНОГО вызывающего. То есть одобрить новую машину можно было только руками в базе.

Обратный ход (обязателен, ПРОВЕРЕН откатом каждой правки по отдельности): вернуть
`issue_local_session` выдачу токена без проверки наличия человека — краснеют
`test_local_session_is_never_issued_for_someone_absent_from_the_copy` и
`test_bridge_never_hands_out_a_token_its_own_cabinet_rejects`;
убрать разбор причины — краснеет `test_unapproved_device_is_named_as_the_reason`;
убрать подстановку машинного device_id в мосте — краснеет
`test_connect_bridge_substitutes_the_machine_device_id`.
"""
import json
import urllib.error
import urllib.request

import pytest

from desktop import local_api

#Поднимаем ТУ ЖЕ инфраструктуру, что и test_login_bridge: настоящее серверное приложение
#на временной базе. Заглушка не заметила бы главного — что выданный токен не открывает
#кабинет ЭТОГО ЖЕ сервера.
from test_login_bridge import (  # noqa: F401  (фикстуры используются pytest)
    _no_real_session, api, _add_user, _post, _get)


#Логин, которого в локальной копии заведомо НЕТ: это и есть чистая машина.
MISSING = "нет-в-копии"


def test_local_session_is_never_issued_for_someone_absent_from_the_copy(api):
    """🔥 Корень. Токен, выписанный человеку, которого в этой базе нет, мёртв по
    построению: `get_current_user` ответит 401 «Пользователь не найден» на первом же
    запросе. Выписывать его — значит выдать сессию, которая гарантированно развалится
    через секунду, вместо того чтобы честно сказать, что не так."""
    access, refresh = local_api.issue_local_session(MISSING, "student")
    assert not access and not refresh, (
        "выписана локальная сессия человеку, которого нет в локальной копии — "
        "кабинет отвергнет её на первом же запросе")


def test_bridge_never_hands_out_a_token_its_own_cabinet_rejects(api, monkeypatch):
    """Свойство, а не слепок: ответил 200 с токеном — этот токен ОБЯЗАН открывать
    `/web/*` того же сервера. Проверяем именно связку, потому что порознь обе половины
    выглядят исправными: вход отвечает 200, кабинет отвечает 401, и каждый по-своему прав."""
    monkeypatch.setattr(local_api, "_try_local_login", lambda *a, **k: None)
    monkeypatch.setattr(local_api, "switch_user_db", lambda *a, **k: False)
    monkeypatch.setattr(local_api, "_try_remote_login",
                        lambda *a, **k: ({"access_token": "prod-a", "refresh_token": "prod-r",
                                          "role": "teacher", "name": "Тестов Т."}, ""))
    #⚠️ Зеркало отчитывается об УСПЕХЕ намеренно (правка после возражения Полковника).
    #Сначала здесь стояла неудача — и тест был зелёным без починки: мост отвечал 403
    #раньше выдачи токена, ветка `if code == 200` не выполнялась НИКОГДА, а главный
    #assert про кабинет не проверял ничего. Успех зеркала при отсутствующем в копии
    #человеке — это ровно тот путь, где раньше и выдавался мёртвый токен.
    monkeypatch.setattr(local_api, "_wait_for_mirror", lambda login, seconds=12: (True, ""))

    code, body = _post(api, "/auth/login", {"login": MISSING, "password": "любой"})
    if code == 200:
        token = body.get("access_token") or ""
        assert token, "успех без токена — контракт входа сломан"
        assert _get(api, "/web/student/overview", token) != 401, (
            "мост отдал токен, который его же кабинет отвергает: человек «войдёт» и "
            "через секунду окажется на форме входа")
    else:
        assert body.get("detail"), "отказ обязан называть причину"


def test_blocking_network_never_runs_on_the_event_loop(api):
    """Структурный сторож (возражение Полковника). Локальный сервер — ОДИН цикл событий:
    блокирующий `httpx`/`sleep` прямо в `async def` останавливает не свой запрос, а ВЕСЬ
    сервер — ни SPA, ни журнала, ни `/health`. Больнее всего это бьёт по тому самому
    человеку, который и так не может войти: экран подтверждения устройства опрашивает
    состояние каждые несколько секунд, и каждый опрос занимал бы цикл до таймаута.

    Проверяем СВОЙСТВО, а не список функций: в теле любого `async def` этого файла нет
    ни синхронного сетевого вызова, ни `time.sleep`. Новая ручка, написанная завтра «как
    проще», краснеет сразу.

    Разбор построчный, а не регулярками: границу функции задаёт отступ, и по нему её
    видно надёжнее, чем любым выражением."""
    import inspect

    BLOCKING = ("httpx.request(", "httpx.get(", "httpx.post(", "httpx.put(",
                "httpx.delete(", "requests.get(", "requests.post(", "requests.request(",
                "time.sleep(")
    offenders = []
    lines = inspect.getsource(local_api).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("async def "):
            indent = len(line) - len(line.lstrip())
            name = stripped.split("(")[0].replace("async def ", "").strip()
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.strip() and (len(cur) - len(cur.lstrip())) <= indent:
                    break
                body = cur.split("#")[0]
                for bad in BLOCKING:
                    if bad in body:
                        offenders.append(name + ": " + bad)
                i += 1
            continue
        i += 1

    assert offenders == [], (
        "блокирующий вызов в цикле событий: " + "; ".join(offenders) +
        ". Оберни в run_in_threadpool — иначе на время вызова замирает весь локальный "
        "сервер, включая журнал и /health.")


def test_unapproved_device_is_named_as_the_reason(api, monkeypatch):
    """Причина обязана быть ДЕЙСТВИЕМ, а не констатацией. 403 с текстом про устройство —
    это ровно то, на что SPA уже умеет показывать экран подтверждения (LoginPage.vue:
    `if (e.response?.status === 403) needApproval.value = true`). Ответ 401/«неверный
    пароль» отправил бы человека менять пароль, которого он не терял."""
    monkeypatch.setattr(local_api, "_try_local_login", lambda *a, **k: None)
    monkeypatch.setattr(local_api, "switch_user_db", lambda *a, **k: False)
    monkeypatch.setattr(local_api, "_try_remote_login",
                        lambda *a, **k: ({"access_token": "prod-a", "role": "teacher"}, ""))
    monkeypatch.setattr(local_api, "_wait_for_mirror",
                        lambda login, seconds=12: (
                            False, "403 Client Error: Forbidden for url: /sync/pull"))

    code, body = _post(api, "/auth/login", {"login": MISSING, "password": "любой"})
    assert code == 403, f"барьер устройства должен приходить как 403, пришло {code}: {body}"
    assert "устройств" in (body.get("detail") or "").lower(), body


def test_network_failure_is_not_called_a_device_problem(api, monkeypatch):
    """Обратная половина: зеркало не доехало из-за сети — это 503, а не 403. Иначе
    человек пошёл бы искать администратора там, где надо было проверить интернет."""
    monkeypatch.setattr(local_api, "_try_local_login", lambda *a, **k: None)
    monkeypatch.setattr(local_api, "switch_user_db", lambda *a, **k: False)
    monkeypatch.setattr(local_api, "_try_remote_login",
                        lambda *a, **k: ({"access_token": "prod-a", "role": "teacher"}, ""))
    monkeypatch.setattr(local_api, "_wait_for_mirror",
                        lambda login, seconds=12: (False, "ConnectTimeout: истекло ожидание"))

    code, body = _post(api, "/auth/login", {"login": MISSING, "password": "любой"})
    assert code == 503, f"сетевой сбой не должен выглядеть как отказ доступа: {code} {body}"


def test_mirror_failure_is_not_swallowed(api):
    """Структурный сторож. Раньше `_wait_for_mirror` звал `mirror_once()` под голым
    `except Exception: pass` и выбрасывал результат — а в нём лежала ЕДИНСТВЕННАЯ
    строка, объясняющая, почему копия пуста. Проглоченная ошибка здесь стоит суток
    гадания на чужой машине."""
    import inspect
    src = inspect.getsource(local_api._wait_for_mirror)
    assert "error" in src, "результат mirror_once обязан читаться, а не выбрасываться"
    bridge = inspect.getsource(local_api.install_login_bridge)
    assert "_wait_for_mirror" in bridge and "mirror_failure_response" in bridge, \
        "мост обязан разбирать причину неудачи зеркала, а не игнорировать её"


def test_mirror_failure_classifier_covers_both_doors():
    """Разбор причины — чистая функция, её проверяем напрямую и на границах."""
    assert local_api.mirror_failure_response("403 Client Error: Forbidden")[0] == 403
    assert local_api.mirror_failure_response("Устройство не подтверждено")[0] == 403
    assert local_api.mirror_failure_response("нет активной сессии с сервером")[0] == 403, \
        ("вход по сети только что прошёл — значит сеть есть; если синхронизация при этом "
         "не получила сессию, самая частая причина именно барьер устройства")
    assert local_api.mirror_failure_response("ConnectTimeout")[0] == 503
    assert local_api.mirror_failure_response("")[0] == 503


# ── Путь наружу: запрос подтверждения устройства с десктопа ──────────────────────────
def test_connect_bridge_substitutes_the_machine_device_id(api, monkeypatch):
    """🔒 Мост подтверждения обязан подставлять device_id ЭТОЙ МАШИНЫ, а не тот, что
    прислала страница.

    У браузера свой идентификатор (localStorage, `api/tokens.js`), у десктопа — свой
    (`app_settings.get_device_id()`), и барьер на боевом сервере смотрит ИМЕННО на
    десктопный: им ходит синхронизация. Одобрив браузерный, администратор одобрил бы
    не ту машину — запрос ушёл бы в никуда, а человек так и остался бы за дверью,
    причём с полной уверенностью, что всё сделал правильно."""
    sent = {}

    def _fake_forward(method, path, payload=None, params=None):
        sent["path"] = path
        sent["payload"] = dict(payload or {})
        sent["params"] = dict(params or {})
        return 200, {"status": "pending"}

    monkeypatch.setattr(local_api, "_forward_to_server", _fake_forward)
    monkeypatch.setattr(local_api, "machine_device_id", lambda: "МАШИНА-1")

    code, _ = _post(api, "/connect/request",
                    {"device_id": "браузерный-подложный", "hostname": "ПК-каб-208"})
    assert code == 200, "мост подтверждения устройства не отвечает"
    assert sent["payload"].get("device_id") == "МАШИНА-1", (
        f"на сервер ушёл чужой device_id: {sent['payload']}")


def test_connect_bridge_never_trusts_the_device_id_from_the_page(api):
    """Структурный сторож к предыдущему: единственным источником device_id обязана быть
    машина. Токеном этот мост закрыть НЕЛЬЗЯ по существу — подтверждение устройства
    происходит ДО входа, токена ещё нет; защита здесь в том, что запрос всегда касается
    только этой машины, а одобряет его живой администратор кодом. Стороннюю страницу
    отсекает общая заслонка origin (`install_origin_guard`), она стоит снаружи всех
    маршрутов."""
    import inspect
    src = inspect.getsource(local_api.install_connect_bridge)
    body = src.split("_connect_request")[1]
    assert "machine_device_id()" in body, "device_id обязан браться у машины"
    assert 'get("device_id")' not in src, (
        "device_id из тела запроса не должен попадать на сервер: страница знает "
        "БРАУЗЕРНЫЙ идентификатор, а барьер смотрит на машинный")
