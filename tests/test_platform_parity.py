"""
test_platform_parity.py — раздел, который есть на сайте, обязан работать и в программе
(сверка платформ по просьбе тестеров, 20.09.2026).

━━ КАК ЛОМАЕТСЯ ПАРИТЕТ У НАС ━━
Не «кнопки нет», а хуже: кнопка есть, экран открывается, список ПУСТ. Внутри десктопной
программы интерфейс тот же самый, но данные он берёт у ЛОКАЛЬНОГО сервера, поднятого на
127.0.0.1. Если сущность не входит в `SYNC_MODELS`, в локальной копии её нет и быть не
может — и человек делает вывод «жалоб нет», «никто не приглашён», «журнал безопасности
чист». Ровно это уже случалось с заявками на регистрацию (`/web/admin/registrations`).

Единственное лекарство — пересылка на бой (`local_api._PROXY_PREFIXES`).

⚠️ Тест сверяет ДВА СПИСКА, которые ведутся в разных местах и разными людьми: адреса,
которые зовёт САЙТ (`web/src/api/endpoints.js`), и то, что программа пересылает. Это
свойство, а не снимок: новый раздел, читающий несинкуемые данные, покраснеет сам.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `/web/admin/messenger` из `_PROXY_PREFIXES` — краснеет
первый тест (именно с этого дефекта сверка и началась).
"""
import io
import pathlib
import re

from desktop import local_api

ROOT = pathlib.Path(__file__).resolve().parents[1]

#Разделы сайта, ЧЬИ ДАННЫЕ ЖИВУТ ТОЛЬКО НА БОЮ. У каждой строки названа сущность и
#почему её нет в локальной копии — проверяет человек на ревью, не машина.
ONLINE_ONLY_SECTIONS = {
    "/web/admin/messenger": "переписка и жалобы вне SYNC_MODELS (§5.4)",
    "/web/admin/audit": "AuditEvent — след БОЕВОЙ машины, не синкуется",
    "/web/admin/invites": "StudentInvite не в SYNC_MODELS; ссылка нужна живая, на бою",
    "/web/admin/registrations": "RegistrationRequest не в SYNC_MODELS",
    "/web/admin/parents": "ParentLink не в SYNC_MODELS",
    "/web/messenger": "сам мессенджер",
    "/me/events": "NotifyEvent не в SYNC_MODELS",
}


def _web_paths() -> set:
    src = (ROOT / "web" / "src" / "api" / "endpoints.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    return set(re.findall(r"api\.\w+\(\s*[`'\"]([^`'\"$]+)", src))


def test_every_online_only_section_is_forwarded_from_the_desktop():
    missing = [p for p in ONLINE_ONLY_SECTIONS
               if not p.startswith(local_api._PROXY_PREFIXES)]
    assert not missing, (
        "внутри программы эти разделы открываются ПУСТЫМИ, потому что их данных нет в "
        "локальной копии и они не пересылаются на бой: "
        + ", ".join(f"{p} ({ONLINE_ONLY_SECTIONS[p]})" for p in missing))


def test_the_site_really_calls_these_sections():
    """Список выше не должен превратиться в кладбище: раздел переименовали — заметим.

    Без этой проверки запись могла бы годами охранять адрес, которого на сайте больше
    нет, — и создавать уверенность, что паритет проверен.
    """
    paths = _web_paths()
    for section in ONLINE_ONLY_SECTIONS:
        assert any(p.startswith(section) for p in paths), (
            f"сайт больше не зовёт {section} — запись в реестре устарела, "
            f"а сторож продолжал бы делать вид, что что-то проверяет")


def test_the_journal_itself_is_never_forwarded():
    """Обратная сторона: пересылать журнал и расписание НЕЛЬЗЯ — они обязаны открываться
    без сети. Иначе offline-first, ради которого десктоп и существует, перестаёт быть."""
    for path in ("/web/teacher/journal", "/web/student/overview", "/web/schedule",
                 "/web/vector/ask", "/sync/pull", "/sync/push"):
        assert not path.startswith(local_api._PROXY_PREFIXES), (
            f"{path} уехал бы на сервер — программа перестала бы работать без интернета")
