"""
conftest.py — Общие фикстуры для тестов серверного API.

Главное: переменные окружения задаём ДО импорта app.* — config.py и db.py читают
GRADEBOOK_DB_URL на этапе импорта и создают движок один раз. Поэтому изолированную
тестовую БД (временный SQLite-файл) прописываем здесь, в самом верху модуля, пока
ни один модуль приложения ещё не импортирован.

Перед каждым тестом таблицы пересоздаются с нуля, а счётчики анти-брутфорса
сбрасываются — тесты не влияют друг на друга.
"""
import os
import tempfile

#Изолированная БД и предсказуемый секрет — строго до импорта приложения.
_TMP_DB = os.path.join(tempfile.gettempdir(), "gradebook_test.db")
os.environ["GRADEBOOK_DB_URL"] = "sqlite:///" + _TMP_DB.replace("\\", "/")
os.environ["GRADEBOOK_JWT_SECRET"] = "test-secret-not-for-production"
#⚠️ Ключ шифрования БД гасим ЯВНО (пустой строкой, а не удалением). `app/config.py`
#дочитывает `server/.env` через `os.environ.setdefault`, то есть занимает любую
#ОТСУТСТВУЮЩУЮ переменную — и тестовая база начинала открываться боевым ключом из
#.env, как только на машине появлялся драйвер sqlcipher3. Тесты падали «file is not a
#database» на ровном месте, причём только у того, кто драйвер поставил.
os.environ["GRADEBOOK_DB_KEY"] = ""
#Барьер подтверждения устройств: даём тестам предсказуемый device_id хоста, чтобы
#обычные запросы проходили барьер «как хост» (connect.device_allowed). Тесты самого
#барьера используют ДРУГИЕ device_id, чтобы проверить отказ/одобрение.
HOST_DEVICE_ID = "test-host-device"
os.environ["GRADEBOOK_HOST_DEVICE_ID"] = HOST_DEVICE_ID

# 🔥 ТА ЖЕ ГРАБЛЯ, ЧТО С GRADEBOOK_DB_KEY ВЫШЕ, — и она была ШИРЕ, чем один ключ.
# `config.py` дочитывает `server/.env` через `setdefault`, то есть занимает ЛЮБУЮ
# отсутствующую переменную. У кого файл есть (машина разработчика) — одно поведение,
# у кого нет (CI) — другое. Найдено 29.08.2026: 436 серверных тестов падали локально
# и проходили в CI, потому что из .env приезжал `GRADEBOOK_ALLOWED_ORIGINS`, а
# `config.IS_PROD` выводится из него. То есть «1146 зелёных» у разных людей означали
# РАЗНЫЕ прогоны, и никто этого не знал.
#
# ⚠️ Гасим ЯВНО и все, от которых зависит поведение, а не только замеченную:
#   • ALLOWED_ORIGINS → IS_PROD (боевые проверки, обязательность второго фактора);
#   • DATA_KEY/INDEX_KEY → шифрование полей ПДн «Кузнечик» (у кого ключи есть —
#     тесты идут по другой ветке кода);
#   • DOMAIN → адреса в ответах и ссылки в письмах.
# Тесты, которым нужен «бой», включают его САМИ (monkeypatch на config.IS_PROD).
os.environ["GRADEBOOK_ALLOWED_ORIGINS"] = "*"
os.environ["GRADEBOOK_DATA_KEY"] = ""
os.environ["GRADEBOOK_INDEX_KEY"] = ""
os.environ["GRADEBOOK_DOMAIN"] = ""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine
from app import throttle, events, connect, msg_limit, activity_state


@pytest.fixture()
def client():
    """Чистый клиент на пустой БД: пересоздаём таблицы, сбрасываем троттлинг и монитор.
    По умолчанию шлёт X-Device-Id хоста — так существующие тесты проходят барьер."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    throttle.reset()
    events.reset()
    connect.reset()
    msg_limit.reset()          #анти-флуд мессенджера — иначе счётчик копится между тестами
    #Ход активностей живёт в ПАМЯТИ процесса (см. app/activity_state.py) и пересоздание
    #таблиц его не трогает: активность из прошлого теста ловилась бы в следующем как
    #«уже идёт» (409). Та же грабля, что была с `throttle.reset()` и словарём остуды.
    activity_state.reset()
    with TestClient(app) as c:
        c.headers.update({"X-Device-Id": HOST_DEVICE_ID})
        yield c


def make_admin(client, login="admin", password="adminpass1"):
    """Заводит первого администратора и возвращает заголовок Authorization."""
    r = client.post("/auth/bootstrap-admin",
                    json={"login": login, "password": password, "full_name": "Админ"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_teacher(client, admin_headers, login="teacher1", password="teacherpass1",
                 subjects=("Математика",)):
    """Заводит преподавателя (через push админа) и возвращает его заголовок Authorization.
    Хеш пароля считаем тем же алгоритмом, что и сервер — пользователь приходит уже хешем."""
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"teach:{login}", "role": "teacher", "login": login,
        "password_hash": hash_password(password), "full_name": "Преподаватель",
        "subjects": list(subjects),
    }]}}, headers=admin_headers)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def assign_teacher(client, admin_headers, teacher_id: str, group: str, subject: str,
                   year: str = "", semester: int = 0):
    """Назначает преподавателя на (группа,предмет) — §ролей препод↔предмет↔группа (3.3.1).

    С этой миграции ролевой скоуп преподавателя строится ТОЛЬКО по явным назначениям
    (webdata.teacher_assignments: таблица subject_hours.teacher_id), не по факту «предмет
    числится у препода» — без этого вызова он не увидит группу вообще (404/403/пустой
    journal). Группу заводить/иметь Subject-предмет в каталоге НЕ обязательно — назначение
    не проверяет Group.subjects, только принадлежность предмета преподавателю."""
    payload = {"group": group, "teachers": {subject: teacher_id}}
    if year:
        payload["year"] = year
    if semester:
        payload["semester"] = semester
    r = client.post("/web/admin/group-hours", json=payload, headers=admin_headers)
    assert r.status_code == 200, r.text
