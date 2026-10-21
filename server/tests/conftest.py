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

# 🔥 СОБРАННЫЙ САЙТ — ТОЖЕ ОКРУЖЕНИЕ, И ЗАДАВАТЬ ЕГО ОБЯЗАН ТЕСТ, А НЕ МАШИНА (21.09.2026).
# `main._find_web_dist` ищет `web/dist` рядом с репозиторием, а появляется он только после
# `npm run build`. У разработчика папка есть, в серверной задаче CI её нет — и сервер
# честно отвечал «интерфейс не собран» (503) на любой адрес. Двадцать проверок
# test_spa_fallback и test_public_schedule краснели в CI с 04.09.2026 и зеленели у нас.
# Проверяют они МАРШРУТИЗАЦИЮ (адрес API → 404, адрес страницы → страница), а не сборку,
# поэтому им хватает минимальной оболочки. Режим «сайта нет» стережёт
# test_no_dist_notice.py — он переопределяет эту переменную сам.
_TEST_DIST = os.path.join(tempfile.gettempdir(), "gradebook_test_dist")
os.makedirs(_TEST_DIST, exist_ok=True)
with open(os.path.join(_TEST_DIST, "index.html"), "w", encoding="utf-8") as _fh:
    _fh.write('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
              '<title>GradeBookAI</title></head><body><div id="app"></div></body></html>')
os.environ["GRADEBOOK_WEB_DIST"] = _TEST_DIST

# 🔒 СЕРВЕРНЫЙ ПРОГОН ГЕРМЕТИЧЕН (17.10.2026) — тем же приёмом, что клиентский
# (`tests/conftest.py` в корне, 05.09.2026). Найдено при разборе медленного прогона: каждый
# тест открывает `TestClient(app)`, то есть заново запускает службу, а её старт звал
# `schedule_web.warm()` — фоновые сборщики полного расписания с НАСТОЯЩЕГО портала ВСГУТУ,
# десятки GET-запросов на категорию. Они делили процессор с тестами, ходили на чужой боевой
# сайт и делали прогон зависимым от интернета. Петля разрешена (локальные серверы стендов).
import socket as _socket

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", "", None})


def _host_of(address):
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def _is_local(host) -> bool:
    h = str(host or "").strip().strip("[]").lower()
    return h in _ALLOWED_HOSTS or h.startswith("127.")


def _blocked(host):
    return RuntimeError(
        "серверный тест пытается открыть соединение НАРУЖУ (%r). Прогон обязан быть "
        "герметичным: он не зависит от интернета и не трогает чужие сайты. Подмени "
        "сетевой вызов заглушкой в самом тесте." % (host,))


_real_create_connection = _socket.create_connection
_real_socket_connect = _socket.socket.connect
_real_socket_connect_ex = _socket.socket.connect_ex


def _guarded_create_connection(address, *a, **kw):
    if not _is_local(_host_of(address)):
        raise _blocked(_host_of(address))
    return _real_create_connection(address, *a, **kw)


def _guarded_socket_connect(self, address, *a, **kw):
    if isinstance(address, (tuple, list)) and not _is_local(_host_of(address)):
        raise _blocked(_host_of(address))
    return _real_socket_connect(self, address, *a, **kw)


def _guarded_socket_connect_ex(self, address, *a, **kw):
    if isinstance(address, (tuple, list)) and not _is_local(_host_of(address)):
        raise _blocked(_host_of(address))
    return _real_socket_connect_ex(self, address, *a, **kw)


_socket.create_connection = _guarded_create_connection
_socket.socket.connect = _guarded_socket_connect
_socket.socket.connect_ex = _guarded_socket_connect_ex

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine
from app import throttle, events, connect, msg_limit, activity_state, shared_state

# ⚡ ДЕШЁВЫЙ ХЕШ ПАРОЛЯ В ПРОГОНЕ (17.10.2026). Замер на машине разработчика: хеш на
# 200 000 итераций SHA-512 — 0.18 с, проверка — столько же, а типичный тест заводит и
# логинит трёх-четырёх человек: ~1.5 с на тест одним хешированием. Формат хеша
# самоописываемый (число итераций лежит в нём, проверка берёт его оттуда), поэтому
# тестовые хеши проверяются ТЕМ ЖЕ кодом, что боевые. Боевую стоимость держит
# `test_password_cost.py`: он читает константу из ИСХОДНИКА, а не из подменённого модуля.
from app import security as _security
_security._SHA_ITERS = 1_000

# Прогрев снимка расписания на старте службы — для боя (см. `main.WARM_SCHEDULE_ON_START`).
# В прогоне служба стартует на КАЖДОМ тесте, и фоновые сборщики только делили бы процессор.
# Сам `warm()` стережёт `test_schedule_warm.py` — прямым вызовом.
import app.main as _main
_main.WARM_SCHEDULE_ON_START = False

# 🔥 СХЕМА НУЖНА УЖЕ ПРИ СБОРКЕ ТЕСТОВ, А НЕ ТОЛЬКО В ФИКСТУРЕ `client` (21.09.2026).
# Часть модулей читает базу при импорте: берёт текущий термин из продукта
# (`YEAR, SEM = _current_term()`). Таблицы же заводила только фикстура — то есть ПОСЛЕ
# сборки. У разработчика это проходило, потому что `gradebook_test.db` во временной папке
# переживает прогоны вместе с таблицами — и с ДАННЫМИ последнего теста прошлого прогона.
# В CI файла нет: четыре модуля 3.9.8 падали «no such table: config», а ошибка сборки
# обрывает ВЕСЬ серверный прогон (воспроизведено: 1820 собрано, 4 ошибки, 0 выполнено).
# Опаснее второе: локально термин вычислялся из остатков прошлого прогона и мог проверять
# не тот сценарий. Пустая схема на старте делает сборку одинаковой на любой машине.
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


def _forget_sync_anchor():
    import os
    from app import sync_clock
    for path in (sync_clock.anchor_path(), sync_clock.restored_mark_path()):
        if path and os.path.exists(path):
            os.remove(path)


_forget_sync_anchor()


def fresh_app_state():
    """Пустая база и сброшенное состояние процесса — то, с чего начинает каждый тест.

    Вынесено из фикстуры `client` (07.10.2026), чтобы набор, который строит свой мир ОДИН
    раз на модуль (карта ответов Вектора), начинал ровно с того же: вторая копия этих
    строк отстала бы при первом же новом сбросе, и чужое состояние утекало бы в неё
    только в общем прогоне — поодиночке модуль оставался бы зелёным."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    #Пустая база на месте прежней — это свежая установка, а не восстановление из копии:
    #якорь прошлого теста (`sync_clock.check_restore`) иначе засчитал бы её подменой.
    _forget_sync_anchor()
    throttle.reset()
    events.reset()
    connect.reset()
    msg_limit.reset()          #анти-флуд мессенджера — иначе счётчик копится между тестами
    #Ход активностей живёт в ПАМЯТИ процесса (см. app/activity_state.py) и пересоздание
    #таблиц его не трогает: активность из прошлого теста ловилась бы в следующем как
    #«уже идёт» (409). Та же грабля, что была с `throttle.reset()` и словарём остуды.
    activity_state.reset()
    #Общее состояние процесса (`app/shared_state.py`) тоже переживает пересоздание
    #таблиц. С 20.09.2026 в нём живёт ТИХОЕ ОКНО пушей: после первого уведомления об
    #оценке следующие десять минут телефон молчит. Без сброса второй тест в наборе
    #получал пустой список отправленных пушей и падал `IndexError` — причём падал бы
    #ТОЛЬКО в наборе, а поодиночке зеленел: ровно тот случай, который мы уже разбирали
    #с троттлингом и ходом активностей.
    shared_state.reset_for_tests()


def honest_head_object(key: str) -> dict:
    """Подменник `storage.head_object` для тестов без сети: хранилище честно отвечает,
    что лёг ровно заявленный файл (размер и тип — из записи вложения).

    ⚠️ Не `lambda key: {}`. С 17.10.2026 пустой ответ значит «объекта НЕТ», и
    подтверждение на него отвечает 409 — раньше тот же `{}` молча считался «не узнали,
    верим заявленному», и тесты проходили мимо проверки, которую должны были задевать."""
    from app.db import SessionLocal
    from app.models import Attachment
    db = SessionLocal()
    try:
        a = db.query(Attachment).filter(Attachment.storage_key == key).first()
        return {"size": int(a.size or 0), "mime": a.mime or ""} if a is not None else {}
    finally:
        db.close()


@pytest.fixture()
def client():
    """Чистый клиент на пустой БД: пересоздаём таблицы, сбрасываем троттлинг и монитор.
    По умолчанию шлёт X-Device-Id хоста — так существующие тесты проходят барьер."""
    fresh_app_state()
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
