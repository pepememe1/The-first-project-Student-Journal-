"""
test_device_policy.py — Веб-политика барьера подтверждения устройства по ролям.

Действующая политика (§11 CLAUDE.md, deps.device_barrier_applies):
  • БРАУЗЕР и МОБИЛЬНОЕ ПРИЛОЖЕНИЕ — барьер не применяется НИ К ОДНОЙ РОЛИ, включая
    admin (защита: верные креды + анти-брутфорс + HTTPS + role-scoped /web/*);
  • ДЕСКТОП (и любой не-веб клиент) — жёсткий барьер как прежде (инвариант §6 цел).

⚠️ В шапке этого файла раньше стояло «ПЕРСОНАЛ в браузере — только после веб-
подтверждения устройства». Это было неправдой ещё до появления мобильного клиента:
код такой ветки не имел (та, что была в routers/auth.py, не исполнялась никогда —
удалена 21.08.2026). Держать в тестовом файле описание НЕ ТОЙ политики опаснее, чем
не иметь описания вовсе: именно сюда идут смотреть, «чем защищён администратор».

Веб-клиент опознаётся заголовком X-Client: web, мобильный — X-Client: android.
Неодобренный браузер/телефон шлёт СВОЙ X-Device-Id (не host, не одобрен).
"""
from conftest import make_admin
from app.security import hash_password

WEB_DEV = {"X-Device-Id": "browser-unapproved", "X-Client": "web"}
DESKTOP_DEV = {"X-Device-Id": "desktop-unapproved"}  # без X-Client — это не веб
ANDROID_DEV = {"X-Device-Id": "phone-unapproved", "X-Client": "android"}


def _add_student(client, admin, login="stud1", password="studpass1"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(password),
        "surname": "Иванов", "name": "Иван", "group_name": "ИС-21",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def _add_teacher(client, admin, login="teacher1", password="teacherpass1"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"teach:{login}", "role": "teacher", "login": login,
        "password_hash": hash_password(password), "full_name": "Преподаватель",
        "subjects": ["Математика"],
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def test_web_student_logs_in_without_approval(client):
    """Студент в браузере с неодобренного устройства входит открыто."""
    admin = make_admin(client)
    _add_student(client, admin)
    r = client.post("/auth/login", json={"login": "stud1", "password": "studpass1"},
                    headers=WEB_DEV)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "student"


def test_web_staff_open_without_approval(client):
    """Политика веба (согласована с заказчиком): ПЕРСОНАЛ в браузере входит открыто, без
    подтверждения устройства — как и студент. Барьер устройства для веба снят целиком
    (см. deps.device_barrier_applies): защита веба — валидные креды + анти-брутфорс +
    HTTPS + role-scoped /web/*. ДЕСКТОП при этом остаётся за жёстким барьером §6
    (см. test_desktop_student_still_barred ниже) — инвариант для десктопа не ослаблен.

    Раньше здесь ожидался 403 (веб-персонал проходил веб-подтверждение устройства). От
    этого отказались по требованию: сайт не должен просить код ни у одной роли."""
    admin = make_admin(client)
    _add_teacher(client, admin)
    r = client.post("/auth/login", json={"login": "teacher1", "password": "teacherpass1"},
                    headers=WEB_DEV)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "teacher"


def test_desktop_student_still_barred(client):
    """ДЕСКТОП-клиент (без X-Client) с неодобренного устройства заблокирован даже для
    студента — жёсткий барьер §6 для десктопа не ослаблен."""
    admin = make_admin(client)
    _add_student(client, admin)
    r = client.post("/auth/login", json={"login": "stud1", "password": "studpass1"},
                    headers=DESKTOP_DEV)
    assert r.status_code == 403, r.text


def test_web_staff_ok_after_web_approval(client):
    """Пройдя веб-подтверждение (request→approve→verify), преподаватель входит с браузера."""
    admin = make_admin(client)
    _add_teacher(client, admin)
    dev = "browser-staff"
    web = {"X-Device-Id": dev, "X-Client": "web"}
    #браузер запрашивает доступ
    client.post("/connect/request", json={"device_id": dev, "hostname": "chrome"}, headers=web)
    #админ одобряет и получает код
    code = client.post("/connect/approve", json={"device_id": dev}, headers=admin).json()["code"]
    #браузер подтверждает код → устройство одобрено
    v = client.post("/connect/verify", json={"device_id": dev, "code": code}, headers=web)
    assert v.status_code == 200, v.text
    #теперь вход персонала проходит
    r = client.post("/auth/login", json={"login": "teacher1", "password": "teacherpass1"},
                    headers=web)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "teacher"


def test_android_admin_logs_in_and_works_without_approval(client):
    """МОБИЛЬНОЕ приложение: администратор входит с неодобренного телефона и ДАЛЬШЕ
    работает — барьер проверяется не только на входе, но и в get_current_user.

    Тест фиксирует фактическую политику, а не желаемую. Она осознанно щедрая (§11), но
    у неё есть цена, которую надо видеть глазами: у мобильной сессии ещё и недельный
    потолок (config.issue_ttl_min), то есть admin с чужого телефона живёт неделю без
    подтверждения устройства. Если политику решат ужесточить — красным станет ИМЕННО
    этот тест, и разговор начнётся с него, а не с обнаружения в проде."""
    make_admin(client)
    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"},
                    headers=ANDROID_DEV)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    token = {"Authorization": f"Bearer {r.json()['access_token']}", **ANDROID_DEV}
    #Барьер стоит и на защищённых ручках — проверяем, что и там телефон не отсекается.
    #⚠️ Адрес был «/me», а такого маршрута НЕТ: запрос уходил в SPA-заглушку и получал
    #200 со страницей. То есть проверка «на защищённых ручках телефон не отсекается»
    #не выполнялась НИ РАЗУ — тест был зелёным, не дойдя до кода. Вскрылось 29.08.2026,
    #когда заглушка перестала проглатывать адреса API (см. app/main.py::_is_api_path).
    me = client.get("/me/prefs", headers=token)
    assert me.status_code == 200, me.text


def test_android_without_client_header_is_still_barred(client):
    """Обратная сторона той же политики: снимает барьер именно ЗАГОЛОВОК, а не телефон.
    Тот же запрос без X-Client — это уже «десктоп», и он упирается в барьер §6.

    Сторож нужен, чтобы `is_web_client` не расширили молча (например, начав опознавать
    клиента по User-Agent): тогда под открытый доступ попал бы и десктопный клиент, а
    вместе с ним `/sync/*` с полным дампом базы."""
    admin = make_admin(client)
    _add_teacher(client, admin)
    r = client.post("/auth/login", json={"login": "teacher1", "password": "teacherpass1"},
                    headers={"X-Device-Id": "phone-unapproved"})
    assert r.status_code == 403, r.text


def test_web_unknown_user_gets_401_not_403(client):
    """Веб: неизвестный логин уходит в обычный 401 (не палим существование аккаунта
    поведением барьера)."""
    make_admin(client)
    r = client.post("/auth/login", json={"login": "nobody", "password": "whatever12"},
                    headers=WEB_DEV)
    assert r.status_code == 401, r.text
