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


def _serve_py() -> str:
    """Текст точки запуска. С 10.09.2026 решения о запуске приняты в ней, а не в юните."""
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1]
            / "serve.py").read_text(encoding="utf-8")


def test_exec_start_pins_the_fast_loop_explicitly(install):
    """uvloop/httptools заданы явно — чтобы пропажа пакета была ГРОМКОЙ.

    Скорости это не добавляет (uvicorn выбирает их сам), но без явности отсутствие
    пакета уводит сервер на медленный asyncio МОЛЧА, и это остаётся незамеченным.

    ⚠️ СВОЙСТВО ТО ЖЕ, МЕСТО ДРУГОЕ. До 10.09.2026 юнит звал uvicorn напрямую, и флаги
    стояли в `ExecStart`. Теперь запуск идёт через `server/serve.py`, поэтому и
    проверять надо ТАМ — иначе сторож остался бы зелёным, глядя на строку, которой уже
    нет, то есть перестал бы стеречь что-либо.
    """
    lines = _exec_start_lines(install)
    assert lines, "в установщике не осталось ExecStart"
    assert any("serve.py" in ln for ln in lines), (
        "ExecStart больше не идёт через serve.py — значит решение о числе процессов "
        "снова принимается строкой в юните, то есть намерением, а не готовностью")

    src = _serve_py()
    assert 'loop="uvloop"' in src and 'http="httptools"' in src, (
        "точка запуска перестала явно задавать uvloop/httptools")


def test_the_installer_never_pins_a_worker_count(install):
    """Число процессов в установщике НЕ ЗАШИВАЕТСЯ — ни числом, ни переменной.

    Записанное здесь `--workers 4` описывало бы намерение и осталось бы прежним, когда
    Redis выключат или перенос состояния окажется незавершённым. Цена несимметрична:
    лишний процесс при поворкерных счётчиках ослабляет анти-брутфорс ровно в N раз,
    молча и при зелёных тестах.
    """
    #⚠️ Смотрим на ИСПОЛНЯЕМЫЕ строки, а не на весь текст. Первая версия этой проверки
    #краснела на комментарии, который объясняет, почему мы так не делаем, — то есть
    #запрещала объяснять запрет. Проверять надо тем же разбором, каким читает
    #потребитель: и bash, и systemd строку, начинающуюся с «#», не исполняют.
    code = "\n".join(ln for ln in install.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "--workers" not in code, (
        "появился --workers: число процессов снова задано намерением")
    assert "GRADEBOOK_WORKERS=" not in code, (
        "установщик прописывает GRADEBOOK_WORKERS — включать несколько процессов "
        "обязан человек, и только когда перенос состояния завершён")


def test_the_launcher_derives_the_worker_count_instead_of_choosing_it(install):
    """🔒 Решение принимается ОДНОЙ функцией, и она смотрит на готовность.

    Проверяем ВЫЗОВ, а не наличие: сторож обязан покраснеть, если строку убрать и
    поставить число. Это наш самый частый класс дефекта — «обещание без вызывающего».
    """
    src = _serve_py()
    assert "workers_allowed()" in src, (
        "точка запуска больше не спрашивает shared_state.workers_allowed() — число "
        "процессов снова выбирается, а не выводится")
    #Приложение обязано уезжать СТРОКОЙ: при нескольких процессах uvicorn импортирует
    #его в каждом сам, и готовый объект туда не переживёт переноса.
    assert '"app.main:app"' in src, (
        "приложение передаётся объектом — при workers>1 uvicorn это не переживёт")


def test_redis_is_local_only_and_optional(install):
    """Общее состояние ставится по классу машины и слушает ТОЛЬКО петлю.

    🔴 Redis по сети добавил бы сетевой отказ на путь КАЖДОГО входа: анти-брутфорс
    спрашивает его ДО сверки пароля. Это была бы наша собственная новая точка отказа, и
    притом в самом чувствительном месте.
    """
    assert "redis-server" in install, "установщик не умеет ставить общее состояние"
    assert "bind 127.0.0.1" in install, (
        "Redis не ограничен петлёй — дверь открыта наружу")
    assert "workstation" in install, (
        "Redis ставится безусловно: на слабой машине несколько процессов бессмысленны, "
        "а лишняя служба ест память, которой и так мало")


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

# ═══════════════════════════════════════════════════════════════════════════════════
# УЖЕСТОЧЕНИЕ БОЕВОГО ЮНИТА (10.09.2026)
#
# 🔥 ПОЧЕМУ ЭТО ПОД ТЕСТОМ, А НЕ «ПРОСТО НАПИСАНО В ЮНИТЕ». Ужесточение systemd —
# редкий случай, когда защита ломает продукт молча и не там, где смотришь. Живой пример
# из этого же захода: `ProtectHome=yes` при коде в /root/gb-deploy делает каталог кода
# НЕВИДИМЫМ процессу — служба не находит собственный serve.py и не поднимается вовсе,
# при безупречном синтаксисе юнита. Поэтому под сторожем не «набор строк», а РЕШЕНИЯ:
# кто владелец процесса, где живёт база, что происходит с домашним каталогом.
# ═══════════════════════════════════════════════════════════════════════════════════

#Обязательный набор из плана Ярослава. Держим списком в ОДНОМ месте: перечисление в
#каждом тесте разошлось бы, а разойтись оно может только в сторону «забыли проверить».
REQUIRED_HARDENING = (
    "NoNewPrivileges=yes",
    "ProtectSystem=strict",
    "PrivateTmp=yes",
    "PrivateDevices=yes",
    "ProtectKernelTunables=yes",
    "ProtectKernelModules=yes",
    "ProtectControlGroups=yes",
    "CapabilityBoundingSet=",
    "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    "SystemCallFilter=@system-service",
)


def unit_text(install):
    """Тело юнита из heredoc `<<UNIT ... UNIT`.

    Разбираем ИМЕННО его, а не весь скрипт: строка `ProtectHome` встречается ещё и в
    пояснении рядом, и проверка по всему файлу зеленела бы от комментария. Это наш
    записанный класс ошибки — сторож, которого обманывает собственный комментарий.
    """
    start = install.index("<<UNIT")
    end = install.index("\nUNIT\n", start)
    return install[start:end]


def missing_hardening(unit):
    """Каких обязательных директив нет. Отдельной функцией — чтобы у сторожа был
    обратный ход: проверку, которую нельзя натравить на заведомо сломанный вход,
    невозможно отличить от сломанной."""
    out = []
    for d in REQUIRED_HARDENING:
        #Сравниваем ПОСТРОЧНО и по началу строки: подстрока `PrivateTmp=yes` нашлась бы
        #и внутри `#PrivateTmp=yes убран потому что…`.
        if not any(line.strip().startswith(d) for line in unit.splitlines()):
            out.append(d)
    return out


def test_service_does_not_run_as_root(install):
    """Прежний юнит стоял с `User=root`: сервер, смотрящий в интернет, имел полные права
    на машину. Любая ошибка разбора запроса становилась не утечкой журнала, а машиной
    целиком."""
    unit = unit_text(install)
    assert "User=gradebook" in unit, "служба обязана работать от отдельного пользователя"
    assert "Group=gradebook" in unit
    assert not any(line.strip() == "User=root" for line in unit.splitlines()), \
        "в юните остался User=root"
    assert "useradd --system" in install, "пользователь gradebook нигде не заводится"


def test_the_whole_required_hardening_set_is_present(install):
    assert missing_hardening(unit_text(install)) == []


def test_the_guard_notices_a_missing_directive(install):
    """Обратный ход. Без него сторож зелен и при исправном юните, и при выпотрошенном."""
    unit = unit_text(install)
    damaged = unit.replace("ProtectSystem=strict", "# убрано нарочно")
    assert "ProtectSystem=strict" in missing_hardening(damaged)
    #И вторая форма: директива есть, но закомментирована — самый вероятный способ
    #«временно отключить и забыть».
    commented = unit.replace("PrivateDevices=yes", "#PrivateDevices=yes")
    assert "PrivateDevices=yes" in missing_hardening(commented)


def test_capability_set_is_empty_not_merely_present(install):
    """`CapabilityBoundingSet=` без значения = ни одной привилегии. Со значением это
    уже совсем другой юнит, а строка выглядит похоже."""
    unit = unit_text(install)
    lines = [ln.strip() for ln in unit.splitlines()]
    assert "CapabilityBoundingSet=" in lines, \
        "набор привилегий должен быть ПУСТЫМ, а не просто объявленным"
    assert "AmbientCapabilities=" in lines


def test_database_lives_outside_the_code_directory(install):
    """Требование «код и release-каталог — только для чтения» держится только если базе
    есть куда писать ВНЕ кода. Иначе пришлось бы открыть на запись сам каталог
    развёртывания — то есть отменить смысл ужесточения: подменивший .py получает
    исполнение кода."""
    unit = unit_text(install)
    assert "StateDirectory=gradebook" in unit
    assert "GRADEBOOK_DB_URL=sqlite:////var/lib/gradebook/" in unit, \
        "база всё ещё в каталоге кода"
    assert "GRADEBOOK_FILES_DIR=/var/lib/gradebook/" in unit, \
        "вложения всё ещё в каталоге кода"


def test_default_install_dir_is_not_inside_a_home_directory(install):
    """🔥 Ровно та мина, о которую споткнулись при написании. `ProtectHome=yes` отрезает
    /root и /home; с кодом в /root/gb-deploy служба не видит собственный serve.py и не
    поднимается СОВСЕМ. Умолчание обязано быть вне домашних каталогов, иначе ужесточение
    отменяет само себя на первом же старте."""
    m = re.search(r'^APP_DIR="([^"]+)"', install, re.M)
    assert m, "не найдено умолчание APP_DIR"
    assert not m.group(1).startswith(("/root", "/home")), (
        "умолчание APP_DIR внутри домашнего каталога: ProtectHome=yes сделает код "
        "невидимым для службы"
    )


def test_home_protection_is_downgraded_loudly_not_silently(install):
    """Оператор вправе указать --dir внутри /root. Тогда ProtectHome понижается — но
    молча понижать защиту нельзя: о ней потом отчитываются как о сделанной."""
    assert 'PROTECT_HOME="read-only"' in install
    assert "ProtectHome=$PROTECT_HOME" in unit_text(install)
    tail = install[install.index('PROTECT_HOME="read-only"'):]
    assert "ВНИМАНИЕ" in tail[:600] or "⚠️" in tail[:600], \
        "понижение ProtectHome происходит без предупреждения"


def test_memory_deny_write_execute_is_not_switched_on_blindly(install):
    """`systemd-analyze security` снимает баллы за отсутствие MemoryDenyWriteExecute, и
    соблазн дописать его ради оценки велик. Нельзя: `cryptography` работает через cffi, а
    libffi создаёт исполняемые замыкания — с этим запретом падает подпись JWT и
    шифрование полей, то есть ВХОД В ЖУРНАЛ. Балл ради неработающего входа — плохой
    размен, и причина обязана остаться записанной рядом."""
    unit = unit_text(install)
    on = [ln for ln in unit.splitlines()
          if ln.strip().startswith("MemoryDenyWriteExecute=")
          and not ln.strip().endswith("=no")]
    assert not on, "MemoryDenyWriteExecute включён — проверьте, что вход ещё работает"
    assert "MemoryDenyWriteExecute" in unit, "решение не записано — вернётся следующим заходом"


def test_installer_verifies_the_service_actually_started(install):
    """«Команду выполнил» — не «служба работает». Ужесточение ломает именно запуск, и
    установщик обязан это заметить сам, а не оставить человеку с мёртвым сервером."""
    assert "systemctl is-active --quiet gradebook" in install
    assert "systemd-analyze security" in install


def test_secrets_are_moved_out_of_the_env_file(install):
    """`secrets_source.py` умеет читать учётные данные systemd с самого начала, но пока
    перенос не сделан НА МАШИНЕ, ключ от базы с ПДн виден в /proc/<pid>/environ любому
    root — включая администратора вуза, которому мы машину отдадим."""
    assert "migrate_secrets_to_credentials.sh" in install
    assert "LoadCredentialEncrypted=" in install


def test_secret_migration_reads_the_names_from_the_product(install):
    """Список имён секретов существует ОДИН раз — в `secrets_source.SECRET_NAMES`.
    Вторая копия в скрипте разошлась бы молча, и первым забытым оказался бы новый
    секрет: он остался бы в .env, а перенос считался бы законченным."""
    path = os.path.join(ROOT, "tools", "migrate_secrets_to_credentials.sh")
    if not os.path.exists(path):
        pytest.skip("tools/migrate_secrets_to_credentials.sh отсутствует")
    text = _read(path)
    assert "SECRET_NAMES" in text and "secrets_source.py" in text
    #И ни одного имени секрета, вписанного руками.
    assert "GRADEBOOK_DB_KEY=" not in text.replace("${name}=", ""), \
        "имя секрета вписано в скрипт переписыванием"


def test_secret_migration_verifies_before_it_strips_the_env(install):
    """🔴 Самое опасное место всего переноса. Вычистить .env, доверившись коду возврата
    шифрования, значит уничтожить единственную копию ключа от базы — а это потеря всех
    данных навсегда, не «неудобство». Обратное чтение обязано стоять ДО очистки."""
    path = os.path.join(ROOT, "tools", "migrate_secrets_to_credentials.sh")
    if not os.path.exists(path):
        pytest.skip("tools/migrate_secrets_to_credentials.sh отсутствует")
    text = _read(path)
    assert "systemd-creds decrypt" in text, "нет обратного чтения"
    assert text.index("systemd-creds decrypt") < text.index('STRIP" = "1"'), \
        "очистка .env стоит РАНЬШЕ проверки — так терять ключ нельзя"
    assert "before-credentials-" in text, "нет резервной копии .env перед очисткой"

