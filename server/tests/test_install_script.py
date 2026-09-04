"""
Сторож установщика нового сервера (`deploy/install.sh`) и шага «прописать службу»
в пошаговом переносе (`desktop/server_admin.py`).

━━ ПОЧЕМУ ЭТО ВООБЩЕ ПОД ТЕСТОМ ━━
Этот скрипт исполняется РОВНО ОДИН РАЗ — в день переезда на машину ВСГУТУ, когда времени
разбираться нет, а старый сервер уже остановлен. Ошибка в нём не «неудобство»: она либо
роняет запуск, либо — что хуже — тихо выключает защиту, и заметят это на проверке.

Проверяются УТВЕРЖДЕНИЯ о содержимом, а не синтаксис bash: разобрать bash по-настоящему
может только bash, а нам важны не скобки, а решения. Тот же приём, что в
`test_caddyfile.py`, и по той же причине.

🔥 ТРИ ДЕФЕКТА, НАЙДЕННЫЕ 04.09.2026 ПРИ ЧТЕНИИ — каждый сработал бы в день переезда:
  1. пакеты ставились РУКОПИСНЫМ списком из пяти штук (в переносе) — без ГОСТ-хеша, без
     SQLCipher, без JWT. Часть отказов громкая, часть ТИХАЯ;
  2. `GRADEBOOK_DB_KEY` не генерировался вовсе — новый сервер работал бы с базой БЕЗ
     шифрования файла, то есть ПДн студентов лежали бы на диске открытым текстом;
  3. в `ExecStart` посреди строки стоял литеральный `\n` — в heredoc он не превращается
     в перенос, и служба падала бы на старте с «unrecognized arguments».
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INSTALL = os.path.join(ROOT, "deploy", "install.sh")
SERVER_ADMIN = os.path.join(ROOT, "desktop", "server_admin.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def install():
    if not os.path.exists(INSTALL):
        pytest.skip("deploy/install.sh отсутствует")     # предмет проверки, не инструмент
    return _read(INSTALL)


@pytest.fixture(scope="module")
def admin():
    if not os.path.exists(SERVER_ADMIN):
        pytest.skip("desktop/server_admin.py отсутствует")
    return _read(SERVER_ADMIN)


# ─────────────────────────────────────────────────────────────────────────────────
# 1. ЗАВИСИМОСТИ — ИЗ ФАЙЛА, А НЕ СПИСКОМ
# ─────────────────────────────────────────────────────────────────────────────────

def _pip_install_lines(text):
    """Строки, ставящие пакеты. `--upgrade pip` не в счёт — это не зависимость продукта."""
    out = []
    for line in text.splitlines():
        if "pip" in line and "install" in line and "upgrade pip" not in line:
            out.append(line.strip())
    return out


def test_installer_takes_dependencies_from_requirements_file(install):
    """Установщик обязан ставить ИЗ requirements.txt."""
    lines = _pip_install_lines(install)
    assert lines, "установщик вообще перестал ставить зависимости"
    assert any("requirements.txt" in ln for ln in lines), (
        "зависимости ставятся не из файла:\n  " + "\n  ".join(lines))


def test_migration_step_takes_dependencies_from_requirements_file(admin):
    """Шаг переноса — тоже. Это и был дефект: пять пакетов, перечисленных руками."""
    lines = _pip_install_lines(admin)
    assert lines, "шаг переноса перестал ставить зависимости"
    assert any("requirements.txt" in ln for ln in lines), (
        "перенос ставит пакеты рукописным списком — на новой машине не встанут ГОСТ-хеш, "
        "шифрование базы и вход:\n  " + "\n  ".join(lines))


@pytest.mark.parametrize("text_name", ["install", "admin"])
def test_no_handwritten_package_list_survives(install, admin, text_name):
    """ОБРАТНЫЙ ХОД: дословная строка, которой дефект и был, не должна вернуться."""
    text = install if text_name == "install" else admin
    assert "install --quiet fastapi uvicorn sqlalchemy" not in text, (
        "вернулся рукописный список пакетов — тот самый, без cryptography и sqlcipher3")


# ─────────────────────────────────────────────────────────────────────────────────
# 2. ШИФРОВАНИЕ БАЗЫ НА НОВОЙ МАШИНЕ
# ─────────────────────────────────────────────────────────────────────────────────

def test_installer_generates_the_database_encryption_key(install):
    """Без GRADEBOOK_DB_KEY новый сервер держит ПДн на диске открытым текстом.

    Отказ ТИХИЙ: продукт работает как ни в чём не бывало, шифрования просто нет.
    Узнать об этом можно только чтением .env или на проверке — то есть слишком поздно.
    """
    assert "GRADEBOOK_DB_KEY=" in install, (
        "установщик перестал генерировать ключ шифрования базы: свежий сервер будет "
        "хранить ПДн студентов открытым текстом")
    assert re.search(r"DBKEY=\$\(openssl rand -hex 32\)", install), (
        "ключ базы должен быть ровно 32 случайных байта (64 hex): db.py откажется "
        "открывать базу с ключом другой длины, и это правильно")


def test_installer_refuses_to_generate_a_new_key_over_an_existing_database(install):
    """🔒 Привезли базу без .env → ОТКАЗ, а не «сделаем как получится».

    Файл базы зашифрован ключом из .env. Сгенерировать новый ключ поверх привезённой
    базы — значит навсегда потерять данные: SQLCipher ответит «file is not a database»,
    и выглядеть это будет как испорченная копия, а не как неверный ключ. На этом уже
    попадались при проверке резервных копий.
    """
    assert "RESTORE_DB" in install, "исчезла возможность привезти базу"
    assert re.search(r"exit\s+3", install), (
        "установщик больше не останавливается, когда база есть, а .env нет — "
        "он сгенерирует новый ключ и данные станут нечитаемыми навсегда")


# ─────────────────────────────────────────────────────────────────────────────────
# 3. СЛУЖБА ЗАПУСКАЕТСЯ
# ─────────────────────────────────────────────────────────────────────────────────

def _exec_start_lines(text):
    return [ln for ln in text.splitlines() if ln.strip().startswith("ExecStart=")]


@pytest.mark.parametrize("text_name", ["install", "admin"])
def test_exec_start_has_no_literal_backslash_n(install, admin, text_name):
    """Литеральный `\\n` посреди команды — служба не поднимется на первом же старте.

    В heredoc обратный слэш с «n» не превращается в перенос строки: systemd получит его
    как отдельный аргумент, uvicorn ответит «unrecognized arguments», и причина будет
    выглядеть как поломка приложения, а не как опечатка в установщике.
    """
    text = install if text_name == "install" else admin
    for line in _exec_start_lines(text):
        assert "\\n" not in line, "в ExecStart остался литеральный \\n:\n  %s" % line


def test_exec_start_pins_the_fast_loop_explicitly(install):
    """uvloop/httptools заданы явно — чтобы пропажа пакета была ГРОМКОЙ.

    Скорости это не добавляет (uvicorn выбирает их сам), но без явности отсутствие
    пакета уводит сервер на медленный asyncio МОЛЧА, и это остаётся незамеченным.
    """
    lines = _exec_start_lines(install)
    assert lines, "в установщике не осталось ExecStart"
    assert any("--loop uvloop" in ln and "--http httptools" in ln for ln in lines), \
        "ExecStart перестал явно задавать uvloop/httptools"


def test_only_one_uvicorn_worker(install):
    """Воркер ОДИН: реестр веб-сокетов и ход активностей живут в памяти процесса."""
    assert "--workers" not in install, (
        "появился --workers: половина участников попадёт в процесс, который про "
        "активность и сокеты не знает")


# ─────────────────────────────────────────────────────────────────────────────────
# 4. БОЕВОЙ КОНФИГ CADDY — ОДИН
# ─────────────────────────────────────────────────────────────────────────────────

def test_installer_uses_the_real_caddyfile_instead_of_writing_its_own(install):
    """Установщик обязан класть КОПИЮ боевого конфига, а не сочинять свой.

    Прежняя версия писала собственный минимальный Caddyfile. Сайт бы поднялся — и
    поэтому дефект был бы незаметен, — но без сжатия (бандл уезжал бы несжатым: 1.3 МБ
    вместо 287 КБ), без таймаутов против slowloris, без лимитов тела, без ротации
    журнала и без раздачи статики из /var/www. Правило проекта: боевой конфиг РОВНО
    ОДИН, всякая вторая копия опасна.
    """
    assert "server/Caddyfile" in install, (
        "установщик больше не берёт боевой Caddyfile из бандла")
    assert "reverse_proxy 127.0.0.1:$PORT" not in install, (
        "установщик снова сочиняет собственный блок сайта — это вторая копия боевого "
        "конфига, и она разойдётся с первой молча")


def test_installer_validates_caddy_config_before_reloading(install):
    """Сломанный конфиг не должен применяться: это положило бы домен."""
    assert "caddy validate" in install, (
        "конфиг применяется без проверки — ошибка в нём уронит сайт целиком")


def test_static_is_not_served_from_root_home(install):
    """Статика раздаётся из /var/www, а не из /root.

    Caddy работает под пользователем `caddy`, а /root имеет права drwx------: раздача
    оттуда даёт 403 НА КАЖДЫЙ АССЕТ. Записанная грабля, оплаченная упавшим сайтом.
    """
    assert "/var/www/gradebook" in install, "исчезла копия статики в /var/www"


# ─────────────────────────────────────────────────────────────────────────────────
# 5. ЖЕЛЕЗО И ТЯЖЁЛЫЙ НАБОР
# ─────────────────────────────────────────────────────────────────────────────────

def test_installer_reports_the_hardware(install):
    """«Увидел новое железо» — прямое требование заказчика к переезду."""
    assert "hostcaps" in install, (
        "установщик перестал показывать железо новой машины")


def test_installer_offers_the_heavy_stack_by_machine_class(install):
    """Тяжёлый набор ставится ПО КЛАССУ МАШИНЫ, а не по тумблеру.

    Настройку, которую надо вспомнить и переключить руками, забывают ровно в день
    переезда — ровно поэтому пакеты и переехали из закомментированных строк в отдельный
    файл, ставящийся автоматически.
    """
    assert "provision_ai_host.py" in install, (
        "установщик больше не ставит тяжёлый набор — перевод и распознавание речи на "
        "новой машине останутся выключенными, и причину будет не найти")


def test_installer_copies_root_level_shared_modules(install):
    """Корневые общие модули (grading.py, study_hours.py, schedule/) обязаны доехать.

    Их отсутствие уже дважды роняло прод при обычном деплое: server/app уезжал, а
    модули, которые он импортирует из корня, — нет.
    """
    assert "schedule" in install and '"$SRC"/*.py' in install, (
        "корневые общие модули больше не копируются — сервер не поднимется")


# ─────────────────────────────────────────────────────────────────────────────────
# 6. ЧЕСТНОСТЬ ПРО ТО, ЧЕГО СКРИПТ НЕ УМЕЕТ
# ─────────────────────────────────────────────────────────────────────────────────

def test_installer_is_honest_about_dns(install):
    """Домен переключает A-запись, а не скрипт. Молчать об этом нельзя.

    Иначе человек уйдёт с ощущением «переезд закончен», а сайт продолжит жить на старом
    VPS — и разница обнаружится в худший момент.
    """
    assert "A-запись" in install, (
        "исчезло предупреждение про DNS: человек решит, что домен уже переехал")
    assert "Старый сервер НЕ трогали" in install, (
        "исчезло указание, что старый сервер цел — без него его выключат раньше времени")
