"""
test_desktop_update.py — автообновление десктопа (3.5.6).

Проверяем ровно то, что на чужом компьютере сломается молча: сравнение версий,
выбор патча, отказ от битого файла и подмену .exe переименованием.

Сеть НЕ трогаем: `urlopen` подменяется. Настоящая закачка проверяется живым прогоном
после сборки, а тесты обязаны быть детерминированными.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import desktop_update as DU


# ── Версии ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("Release 3.5.6", (3, 5, 6)),
    ("3.5.6", (3, 5, 6)),
    ("v3.5.6-test", (3, 5, 6)),
    ("Release 3.6", (3, 6)),
    ("", ()),
    ("без цифр", ()),
])
def test_parse_version(text, expected):
    assert DU.parse_version(text) == expected


def test_is_newer_compares_numerically_not_as_text():
    """Главная ловушка строкового сравнения: «3.5.10» ДОЛЖНА быть новее «3.5.9»."""
    assert DU.is_newer("3.5.10", "3.5.9")
    assert not DU.is_newer("3.5.9", "3.5.10")


def test_is_newer_treats_missing_parts_as_zero():
    assert not DU.is_newer("3.6", "3.6.0")
    assert not DU.is_newer("3.6.0", "3.6")
    assert DU.is_newer("3.6.1", "3.6")


def test_unparseable_version_is_never_newer():
    """Неразборчивый манифест не имеет права запустить обновление: лучше остаться на
    рабочей сборке, чем поставить неизвестно что."""
    assert not DU.is_newer("мусор", "3.5.5")
    assert not DU.is_newer("3.5.6", "мусор")


def test_patch_name_is_single_source_of_truth():
    assert DU.patch_name("Release 3.5.5", "3.5.6") == "3.5.5-3.5.6.patch"


# ── Выбор патча ───────────────────────────────────────────────────────────────────
def _manifest(patches=None, version="3.5.6"):
    return {"version": version,
            "full": {"file": f"GradeBookAI-{version}.exe", "sha256": "f" * 64, "size": 10},
            "patches": patches if patches is not None else []}


def _patch(frm="3.5.5", to="3.5.6"):
    return {"from": frm, "to": to, "file": DU.patch_name(frm, to),
            "sha256": "a" * 64, "target_sha256": "f" * 64, "size": 5}


def test_pick_patch_matches_current_version():
    assert DU.pick_patch(_manifest([_patch()]), "Release 3.5.5")["file"] == "3.5.5-3.5.6.patch"


def test_pick_patch_ignores_patch_from_another_version():
    """Патч 3.5.4→3.5.6 не годится тому, кто сидит на 3.5.5 — иначе наложим на не тот
    файл и получим мусор вместо программы."""
    assert DU.pick_patch(_manifest([_patch("3.5.4", "3.5.6")]), "3.5.5") is None


def test_pick_patch_requires_checksums():
    """Патч без хешей не берём: применить его — записать на диск непроверяемые байты."""
    bad = _patch()
    bad.pop("target_sha256")
    assert DU.pick_patch(_manifest([bad]), "3.5.5") is None


def test_no_patch_when_already_latest():
    assert DU.pick_patch(_manifest([_patch()]), "3.5.6") is None
    assert not DU.has_update(_manifest(), "3.5.6")
    assert DU.has_update(_manifest(), "3.5.5")


# ── Клиент: подмена .exe ──────────────────────────────────────────────────────────
@pytest.fixture()
def updater_env(tmp_path, monkeypatch):
    """Изолированная «установка»: свой каталог программы и свои данные."""
    monkeypatch.setenv("GRADEBOOK_APP_DIR", str(tmp_path))
    monkeypatch.setenv("GRADEBOOK_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(exist_ok=True)
    for mod in ("app_paths", "updater"):
        sys.modules.pop(mod, None)
    from data import updater
    import app_paths
    monkeypatch.setattr(app_paths, "data_dir", lambda: str(tmp_path / "data"))
    monkeypatch.setattr(updater.app_paths, "data_dir", lambda: str(tmp_path / "data"))
    exe = tmp_path / updater.EXE_NAME
    exe.write_bytes(b"OLD-EXE")
    return updater, tmp_path, exe


def _stage(updater, tmp_path, payload=b"NEW-EXE", version="3.5.6"):
    """Кладёт «скачанное обновление» рядом с .exe, как это делает check_and_fetch."""
    new = tmp_path / (updater.EXE_NAME + updater.NEW_SUFFIX)
    new.write_bytes(payload)
    info = {"version": version, "path": str(new), "sha256": DU.sha256_bytes(payload)}
    (tmp_path / "data" / updater.PENDING_NAME).write_text(json.dumps(info), encoding="utf-8")
    return new


def test_apply_pending_replaces_exe_by_rename(updater_env):
    """Подмена именно ПЕРЕИМЕНОВАНИЕМ: Windows не даёт перезаписать запущенный .exe,
    но даёт его переименовать — на этом и держится вся установка."""
    updater, tmp_path, exe = updater_env
    _stage(updater, tmp_path)

    assert updater.apply_pending("3.5.5") is True
    assert exe.read_bytes() == b"NEW-EXE"
    #Старый файл сохранён рядом (пока процесс жив, удалить его нельзя).
    assert (tmp_path / (updater.EXE_NAME + updater.OLD_SUFFIX)).read_bytes() == b"OLD-EXE"
    assert not (tmp_path / "data" / updater.PENDING_NAME).exists()


def test_apply_pending_rejects_corrupted_download(updater_env):
    """Файл побился после скачивания (диск/антивирус) — ставить его нельзя."""
    updater, tmp_path, exe = updater_env
    new = _stage(updater, tmp_path)
    new.write_bytes(b"CORRUPTED")          #хеш в метке больше не сходится

    assert updater.apply_pending("3.5.5") is False
    assert exe.read_bytes() == b"OLD-EXE", "рабочая программа не должна пострадать"
    assert not new.exists(), "битый файл обязан быть убран, а не ждать следующего запуска"


def test_apply_pending_skips_when_already_up_to_date(updater_env):
    """Метка от старого обновления не должна «откатывать» уже обновлённую программу."""
    updater, tmp_path, exe = updater_env
    _stage(updater, tmp_path, version="3.5.5")

    assert updater.apply_pending("3.5.6") is False
    assert exe.read_bytes() == b"OLD-EXE"


def test_apply_pending_without_update_does_nothing(updater_env):
    updater, tmp_path, exe = updater_env
    assert updater.apply_pending("3.5.6") is False
    assert exe.read_bytes() == b"OLD-EXE"


def test_cleanup_old_removes_previous_exe(updater_env):
    updater, tmp_path, _exe = updater_env
    old = tmp_path / (updater.EXE_NAME + updater.OLD_SUFFIX)
    old.write_bytes(b"PREV")
    updater.cleanup_old()
    assert not old.exists()


# ── Интерактивный апдейтер: диалог да/нет, перезапуск ─────────────────────────────
class _FakeUser32:
    """Подмена ctypes.windll.user32 — реальный MessageBoxW НИКОГДА не должен всплывать
    в тестах (завис бы, ожидая клика человека)."""
    def __init__(self, answer=6):
        self.answer = answer
        self.calls = []

    def MessageBoxW(self, hwnd, message, title, flags):
        self.calls.append((message, title, flags))
        return self.answer


def test_ask_yes_no_true_on_idyes(updater_env, monkeypatch):
    updater, _tmp, _exe = updater_env
    fake = _FakeUser32(answer=6)                                # IDYES
    monkeypatch.setattr(updater.ctypes, "windll",
                        type("W", (), {"user32": fake})(), raising=False)
    assert updater.ask_yes_no("Заголовок", "Текст") is True
    assert fake.calls and fake.calls[0][1] == "Заголовок"


def test_ask_yes_no_false_on_idno(updater_env, monkeypatch):
    updater, _tmp, _exe = updater_env
    fake = _FakeUser32(answer=7)                                # IDNO
    monkeypatch.setattr(updater.ctypes, "windll",
                        type("W", (), {"user32": fake})(), raising=False)
    assert updater.ask_yes_no("Заголовок", "Текст") is False


def test_show_info_never_raises_if_dialog_fails(updater_env, monkeypatch):
    """Показ информационного окна — best-effort: сбой не должен ронять программу."""
    updater, _tmp, _exe = updater_env

    class Boom:
        def MessageBoxW(self, *a, **kw):
            raise OSError("нет доступа к рабочему столу")
    monkeypatch.setattr(updater.ctypes, "windll",
                        type("W", (), {"user32": Boom()})(), raising=False)
    updater.show_info("Заголовок", "Текст")                    # не должно бросить


def test_relaunch_noop_when_not_frozen(updater_env, monkeypatch):
    """В dev-запуске (не собранный .exe) перезапускать нечего."""
    updater, _tmp, _exe = updater_env
    called = []
    monkeypatch.setattr(updater.app_paths, "is_frozen", lambda: False)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: called.append(a))
    updater.relaunch()
    assert not called


def test_relaunch_spawns_new_process_when_frozen(updater_env, monkeypatch):
    updater, tmp_path, exe = updater_env
    calls = []
    monkeypatch.setattr(updater.app_paths, "is_frozen", lambda: True)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: calls.append(args))
    updater.relaunch()
    assert calls == [[str(exe)]]


def test_check_and_prompt_no_update_never_asks(updater_env, monkeypatch):
    """Нет обновления — диалог вообще не должен показываться."""
    updater, _tmp, _exe = updater_env
    monkeypatch.setattr(updater, "fetch_manifest", lambda url, timeout=6: _manifest(version="3.5.5"))
    monkeypatch.setattr(updater, "ask_yes_no",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("не должен спрашивать")))
    assert updater.check_and_prompt("https://x", "3.5.5") is False


def test_check_and_prompt_decline_closes_without_downloading(updater_env, monkeypatch):
    """Отказ («нет») — программа должна закрыться, но НИЧЕГО не скачивать."""
    updater, _tmp, _exe = updater_env
    monkeypatch.setattr(updater, "fetch_manifest", lambda url, timeout=6: _manifest())
    monkeypatch.setattr(updater, "ask_yes_no", lambda *a, **kw: False)
    monkeypatch.setattr(updater, "check_and_fetch",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("не должен качать")))
    assert updater.check_and_prompt("https://x", "3.5.5") is True


def test_check_and_prompt_accept_downloads_applies_and_relaunches(updater_env, monkeypatch):
    """Согласие («да») — скачать, установить, перезапустить одним циклом."""
    updater, _tmp, _exe = updater_env
    relaunched = []
    monkeypatch.setattr(updater, "fetch_manifest", lambda url, timeout=6: _manifest())
    monkeypatch.setattr(updater, "ask_yes_no", lambda *a, **kw: True)
    monkeypatch.setattr(updater, "check_and_fetch",
                        lambda *a, **kw: {"version": "3.5.6", "path": "x", "sha256": "f" * 64})
    monkeypatch.setattr(updater, "apply_pending", lambda *a, **kw: True)
    monkeypatch.setattr(updater, "relaunch", lambda: relaunched.append(1))
    assert updater.check_and_prompt("https://x", "3.5.5") is True
    assert relaunched == [1]


def test_check_and_prompt_accept_but_download_fails_falls_back_to_normal_startup(updater_env, monkeypatch):
    """Согласились, но скачать/поставить не вышло — сообщаем и продолжаем как обычно
    (НЕ закрываем программу: сеть подвела — не повод не пустить человека в журнал)."""
    updater, _tmp, _exe = updater_env
    shown = []
    relaunched = []
    monkeypatch.setattr(updater, "fetch_manifest", lambda url, timeout=6: _manifest())
    monkeypatch.setattr(updater, "ask_yes_no", lambda *a, **kw: True)
    monkeypatch.setattr(updater, "check_and_fetch", lambda *a, **kw: {})
    monkeypatch.setattr(updater, "show_info", lambda *a, **kw: shown.append(a))
    monkeypatch.setattr(updater, "relaunch", lambda: relaunched.append(1))
    assert updater.check_and_prompt("https://x", "3.5.5") is False
    assert shown and not relaunched


def test_fetch_manifest_survives_offline(updater_env, monkeypatch):
    """Нет сети — это штатное состояние, а не ошибка: возвращаем пустой манифест."""
    updater, _tmp, _exe = updater_env

    def boom(*a, **kw):
        raise OSError("нет сети")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    assert updater.fetch_manifest("https://example.invalid") == {}


def test_fetch_manifest_empty_url_does_not_touch_network(updater_env, monkeypatch):
    """Пустой адрес сервера (офлайн-режим) — в сеть не ходим вовсе."""
    updater, _tmp, _exe = updater_env
    called = []
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda *a, **kw: called.append(1))
    assert updater.fetch_manifest("") == {}
    assert not called


# ── Дельта: собрать и наложить ────────────────────────────────────────────────────
def test_patch_roundtrip_reconstructs_new_build(tmp_path):
    """Патч, собранный сборщиком, обязан дать БАЙТ-В-БАЙТ новый файл.

    Это контракт между `tools/make_desktop_patch.py` и `data/updater.py`: разъедутся —
    человек получит .exe, который не запустится."""
    zstandard = pytest.importorskip("zstandard")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    import make_desktop_patch as MP

    #Похоже на реальность: две сборки, различающиеся куском в середине.
    old = tmp_path / "old.exe"
    new = tmp_path / "new.exe"
    body = bytes(range(256)) * 400
    old.write_bytes(body + b"VERSION-3.5.5" + body)
    new.write_bytes(body + b"VERSION-3.5.6" + body)
    patch = tmp_path / "p.patch"

    size = MP.build_patch(str(old), str(new), str(patch))
    assert size > 0

    #Накладываем тем же кодом, что и клиент.
    sys.modules.pop("updater", None)
    from data import updater
    out = tmp_path / "out.exe"
    assert updater._apply_patch(str(old), str(patch), str(out)) is True
    assert out.read_bytes() == new.read_bytes()


def test_patch_is_much_smaller_than_full_file(tmp_path):
    """Ради чего всё затевалось: дельта похожих сборок должна быть в разы меньше файла."""
    pytest.importorskip("zstandard")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "tools"))
    import make_desktop_patch as MP

    old = tmp_path / "old.exe"
    new = tmp_path / "new.exe"
    body = os.urandom(2 * 1024 * 1024)       #несжимаемое «тело» сборки
    old.write_bytes(body + b"A" * 1024)
    new.write_bytes(body + b"B" * 1024)
    patch = tmp_path / "p.patch"

    size = MP.build_patch(str(old), str(new), str(patch))
    assert 0 < size < os.path.getsize(new) * 0.2


# ── Защищённый канал (находка аудита 08.08.2026) ──────────────────────────────────
# Автообновление — единственное место продукта, где чужой байт становится
# исполняемым кодом. Тройная сверка SHA-256 от подмены не спасает: хеш едет ТЕМ ЖЕ
# каналом, что и файл. Значит проверять надо канал, а не только содержимое.
@pytest.mark.parametrize("url,allowed", [
    ("https://esstu-gradebook.ru", True),      # боевой адрес
    ("https://192.168.1.50:8443", True),       # свой сервер, но с TLS
    ("http://127.0.0.1:8000", True),           # петля: встать в середину негде
    ("http://localhost:8000", True),
    ("", True),                                # адреса нет вовсе — качать неоткуда
    ("http://194.226.120.74:8000", False),     # боевой IP открытым текстом
    ("http://192.168.1.50:8000", False),       # ровно то, что создаёт «ПК как сервер ЛВС»
    ("http://gradebook.local:8000", False),
])
def test_transport_guard_allows_only_secure_channels(updater_env, url, allowed):
    updater, _tmp, _exe = updater_env
    assert updater._transport_ok(url) is allowed


def test_manifest_over_plain_http_never_touches_network(updater_env, monkeypatch):
    """По небезопасному адресу запрос не делается ВООБЩЕ.

    Важно именно «не делается», а не «результат отбрасывается»: сам факт запроса уже
    сообщает тому, кто сидит в середине, что здесь есть клиент, готовый принять .exe.
    """
    updater, _tmp, _exe = updater_env
    def boom(*a, **kw):                       # pragma: no cover — не должно вызваться
        raise AssertionError("updater полез в сеть по незащищённому каналу")
    monkeypatch.setattr(updater, "_get", boom)
    assert updater.fetch_manifest("http://192.168.1.50:8000") == {}


def test_prompt_over_plain_http_does_not_offer_update(updater_env, monkeypatch):
    """Диалог «установить обновление?» по http не показывается, и программа живёт дальше.

    Возврат False здесь принципиален: True означает «закройся прямо сейчас», и человек
    остался бы без журнала из-за того, что администратор поднял сервер без TLS.
    """
    updater, _tmp, _exe = updater_env
    monkeypatch.setattr(updater, "_get", lambda *a, **kw: json.dumps(
        {"version": "9.9.9", "file": "GradeBookAI.exe", "sha256": "0" * 64}
    ).encode("utf-8"))
    asked = []
    monkeypatch.setattr(updater, "ask_yes_no", lambda *a: asked.append(a) or True)
    assert updater.check_and_prompt("http://192.168.1.50:8000", "3.6.9") is False
    assert not asked, "по незащищённому каналу обновление даже не предлагается"


def test_prompt_over_https_still_offers_update(updater_env, monkeypatch):
    """Обратная сторона: заслонка не должна отключить автообновление на боевом https.

    Без этой проверки «починка» могла бы просто выключить обновления всем и остаться
    незамеченной — тесты были бы зелёными, а продукт перестал бы обновляться.
    """
    updater, _tmp, _exe = updater_env
    monkeypatch.setattr(updater, "_get", lambda *a, **kw: json.dumps(
        {"version": "9.9.9", "file": "GradeBookAI.exe", "sha256": "0" * 64}
    ).encode("utf-8"))
    asked = []
    monkeypatch.setattr(updater, "ask_yes_no", lambda *a: asked.append(a) or False)
    assert updater.check_and_prompt("https://esstu-gradebook.ru", "3.6.9") is True
    assert asked, "по https обновление обязано предлагаться как раньше"
