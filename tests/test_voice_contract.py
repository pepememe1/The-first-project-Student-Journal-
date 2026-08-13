"""
test_voice_contract.py — голосовой ввод обязан выжить при смене оболочки окна.

Зачем именно сейчас. Оболочку десктопа планируется заменить (QtWebEngine → системный
WebView2, чтобы .exe не тащил Chromium). Голосовой ввод — самая хрупкая при таком
переезде способность: он опирается на разрешение микрофона у движка и на то, что
страница и распознаватель живут на ОДНОМ адресе. Проверять это «руками после
миграции» поздно: тишина в микрофоне выглядит как «наверное, драйвер», и правится днями.

Поэтому здесь закреплён КОНТРАКТ, не зависящий от того, чем нарисовано окно:
распознавание отдаёт локальный сервер, за тем же барьером, с того же адреса. Любая
оболочка обязана его соблюдать — а если перестанет, тест скажет об этом сразу.
"""
import os
import tempfile

import pytest

from desktop import local_api


@pytest.fixture(scope="module")
def api():
    tmp = os.path.join(tempfile.mkdtemp(), "voice_test.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен: {srv.error}")
    yield srv
    srv.stop()


def _code(url, token="", method="GET", data=None):
    import urllib.error
    import urllib.request
    headers = {"X-Client": "web"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        import urllib.request as _u
        with _u.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_stt_lives_on_the_local_server(api):
    """Распознавание отдаёт ЛОКАЛЬНЫЙ сервер — значит звук не покидает компьютер (152-ФЗ).
    Тот же адрес, что у страницы: иначе браузерный движок зарежет запрос по CORS."""
    assert _code(api.url("/web/vector/stt/status")) == 401, "статус — за авторизацией"


def test_stt_upload_requires_auth(api):
    """Приём аудио обязан быть за барьером: без него любой процесс на ПК мог бы грузить
    файлы в распознаватель от лица пользователя."""
    assert _code(api.url("/web/vector/stt"), method="POST", data=b"x") == 401


def test_spa_bundle_still_contains_microphone():
    """Кнопка микрофона живёт в СОБРАННОМ интерфейсе. Ловит потерю при пересборке фронта
    (и при смене оболочки, когда фронт собирают заново): без этой проверки исчезновение
    кнопки заметил бы только пользователь."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist = os.path.join(root, "web", "dist", "assets")
    if not os.path.isdir(dist):
        pytest.skip("web/dist не собран (npm run build)")
    blob = ""
    for name in os.listdir(dist):
        if name.endswith(".js"):
            with open(os.path.join(dist, name), encoding="utf-8", errors="ignore") as f:
                blob += f.read()
    assert "/web/vector/stt" in blob, "интерфейс потерял обращение к распознаванию"
    assert "mediaDevices" in blob or "MediaRecorder" in blob, "потеряна запись с микрофона"


def test_voice_module_keeps_recognition_on_the_page_origin():
    """Запрос обязан идти ОТНОСИТЕЛЬНЫМ путём, а не на боевой домен. Абсолютный адрес
    сломал бы и приватность (звук уехал бы с машины), и сам запрос (CORS) — мы этот
    урок уже получили на данных журнала."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "web", "src", "utils", "voiceInput.js")
    with open(src, encoding="utf-8") as f:
        code = f.read()
    assert "'/web/vector/stt'" in code
    assert "esstu-gradebook.ru" not in code, "адрес боевого домена в голосовом вводе"
