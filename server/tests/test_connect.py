"""
test_connect.py — Барьер подтверждения подключения устройств.

Проверяем сквозной поток: неодобренный ПК не входит → запрос → админ видит его →
принимает (код) → ввод кода одобряет устройство → теперь вход проходит. Плюс отказ,
неверный код и пропуск хоста по GRADEBOOK_HOST_DEVICE_ID.
"""
from conftest import HOST_DEVICE_ID

#Заголовок «чужого» (неодобренного) устройства — НЕ равен host device id.
NEW_DEV = {"X-Device-Id": "new-pc-001"}


def test_unapproved_device_cannot_login(client):
    """Неодобренный ПК получает 403 даже с верными кредами."""
    admin = make_admin_headers(client)      #админ заведён (запрос от хоста — проходит)
    make_teacher_via_admin(client, admin, "t1", "passw0rd1")
    #Тот же логин/пароль, но с ЧУЖОГО устройства — барьер закрыт.
    r = client.post("/auth/login", json={"login": "t1", "password": "passw0rd1"},
                    headers=NEW_DEV)
    assert r.status_code == 403, r.text


def make_admin_headers(client):
    """Заголовок админа (бутстрап идемпотентно-устойчив: если уже есть — логинимся)."""
    r = client.post("/auth/bootstrap-admin",
                    json={"login": "admin", "password": "adminpass1", "full_name": "Админ"})
    if r.status_code == 200:
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_full_approval_flow(client):
    """request → admin видит → approve(код) → verify(код) → вход проходит."""
    admin = make_admin_headers(client)
    make_teacher_via_admin(client, admin, "t2", "passw0rd2")

    #1. Новый ПК запрашивает подключение.
    r = client.post("/connect/request",
                    json={"device_id": "new-pc-001", "hostname": "PC-IVANOV"},
                    headers=NEW_DEV)
    assert r.status_code == 200 and r.json()["status"] == "pending", r.text

    #2. Админ видит запрос в списке (с именем ПК).
    r = client.get("/connect/requests", headers=admin)
    assert r.status_code == 200, r.text
    reqs = r.json()["requests"]
    assert any(x["device_id"] == "new-pc-001" and x["hostname"] == "PC-IVANOV"
               for x in reqs)

    #3. Админ принимает → получает 6-значный код.
    r = client.post("/connect/approve", json={"device_id": "new-pc-001"}, headers=admin)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert len(code) == 6 and code.isdigit()

    #4. Неверный код отвергается (400), верный — одобряет устройство.
    r = client.post("/connect/verify", json={"device_id": "new-pc-001", "code": "000000"},
                    headers=NEW_DEV)
    #Маловероятное совпадение случайного кода с 000000 игнорируем: если совпало —
    #устройство уже одобрено, что тоже корректно. Иначе ждём 400.
    if code != "000000":
        assert r.status_code == 400, r.text
    r = client.post("/connect/verify", json={"device_id": "new-pc-001", "code": code},
                    headers=NEW_DEV)
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text

    #5. Теперь вход с этого устройства проходит.
    r = client.post("/auth/login", json={"login": "t2", "password": "passw0rd2"},
                    headers=NEW_DEV)
    assert r.status_code == 200, r.text


def test_reject_flow(client):
    """Отклонённый запрос пропадает из списка, статус для клиента — rejected."""
    admin = make_admin_headers(client)
    client.post("/connect/request", json={"device_id": "new-pc-002", "hostname": "PC-X"},
                headers={"X-Device-Id": "new-pc-002"})
    r = client.post("/connect/reject", json={"device_id": "new-pc-002"}, headers=admin)
    assert r.status_code == 200, r.text
    #Клиент при опросе видит rejected.
    r = client.get("/connect/status", params={"device_id": "new-pc-002"},
                   headers={"X-Device-Id": "new-pc-002"})
    assert r.json()["status"] == "rejected", r.text
    #В активном списке админа его больше нет.
    r = client.get("/connect/requests", headers=admin)
    assert not any(x["device_id"] == "new-pc-002" for x in r.json()["requests"])


def test_host_device_bypasses_gate(client):
    """ПК-хост (X-Device-Id == GRADEBOOK_HOST_DEVICE_ID) проходит без одобрения."""
    admin = make_admin_headers(client)     #сам бутстрап шёл от хоста — уже подтверждает
    make_teacher_via_admin(client, admin, "t3", "passw0rd3")
    r = client.post("/auth/login", json={"login": "t3", "password": "passw0rd3"},
                    headers={"X-Device-Id": HOST_DEVICE_ID})
    assert r.status_code == 200, r.text


def test_already_approved_request_returns_approved(client):
    """Повторный /connect/request с уже одобренного устройства сразу даёт approved."""
    admin = make_admin_headers(client)
    client.post("/connect/request", json={"device_id": "new-pc-003"},
                headers={"X-Device-Id": "new-pc-003"})
    code = client.post("/connect/approve", json={"device_id": "new-pc-003"},
                       headers=admin).json()["code"]
    client.post("/connect/verify", json={"device_id": "new-pc-003", "code": code},
                headers={"X-Device-Id": "new-pc-003"})
    #Устройство одобрено — повторный запрос не плодит ожидание, отвечает approved.
    r = client.post("/connect/request", json={"device_id": "new-pc-003"},
                    headers={"X-Device-Id": "new-pc-003"})
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text


def make_teacher_via_admin(client, admin_headers, login, password):
    """Заводит преподавателя через push админа (без обращения к make_teacher, чтобы
    задать произвольный логин/пароль и не логиниться от его имени тут)."""
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"teach:{login}", "role": "teacher", "login": login,
        "password_hash": hash_password(password), "full_name": "Преподаватель",
        "subjects": ["Математика"],
    }]}}, headers=admin_headers)
    assert r.status_code == 200, r.text
