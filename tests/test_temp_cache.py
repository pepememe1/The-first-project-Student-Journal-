"""
test_temp_cache.py — быстрый старт программы (замер 27.09.2026, шапка `desktop/temp_cache.py`).

Держится:
- кэш в %TEMP% ЗАШИФРОВАН: ФИО преподавателя из снимка расписания не лежит открытым
  текстом в каталоге, общем для всех программ пользователя;
- подложенный или испорченный файл — «кэша нет», а не чужие данные на экране;
- типы файлов страницы берутся без реестра Windows (0.42–0.59 с на каждом запуске) и
  одинаковы на любой машине;
- у обеих правок есть вызывающий в старте локального сервера.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: писать без шифрования — краснеет «ФИО не видно»; принимать файл
без расшифровки (сжатый текст как есть) — краснеет «подделка»; вернуть
`mimetypes.init()` — краснеет «реестр не читается»;
убрать вызов из `start` — краснеют сторожа вызова.
"""
import json
import mimetypes
import os
import zlib

import pytest

from desktop import local_api, temp_cache

SNAP = {"teacher_index": {"Иванова Мария Петровна": {"1": {}}}, "ts": 1.0}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(temp_cache, "cache_dir", lambda: str(tmp_path))
    return tmp_path


def test_roundtrip(cache_dir):
    assert temp_cache.save("schedule-college-full", SNAP)
    assert temp_cache.load("schedule-college-full") == SNAP


def test_teacher_name_is_not_readable_from_the_file(cache_dir):
    temp_cache.save("schedule-college-full", SNAP)
    raw = (cache_dir / "schedule-college-full.bin").read_bytes()
    for enc in ("utf-8", "utf-16-le", "cp1251"):
        assert "Иванова".encode(enc) not in raw
    #И не «просто сжато»: распаковка без ключа ничего не даёт.
    with pytest.raises(zlib.error):
        zlib.decompress(raw[len(temp_cache._FORMAT):])


def test_forged_or_corrupted_file_is_treated_as_missing(cache_dir):
    path = cache_dir / "schedule-college-full.bin"
    #Подделка: правильный формат, но без нашего ключа.
    forged = zlib.compress(json.dumps({"подмена": True}).encode())
    path.write_bytes(temp_cache._FORMAT + forged)
    assert temp_cache.load("schedule-college-full") is None
    #Порча настоящего файла.
    temp_cache.save("schedule-college-full", SNAP)
    blob = bytearray(path.read_bytes())
    blob[-5] ^= 0xFF
    path.write_bytes(bytes(blob))
    assert temp_cache.load("schedule-college-full") is None
    #Чужой формат.
    path.write_bytes(b"xxxx" + bytes(blob))
    assert temp_cache.load("schedule-college-full") is None


def test_name_whitelist_blocks_path_tricks(cache_dir):
    assert temp_cache.save("../../evil", SNAP) is False
    assert temp_cache.load("..\\evil") is None
    assert not any(cache_dir.parent.glob("evil*"))


def test_drop(cache_dir):
    temp_cache.save("schedule-college-index", {"a": 1})
    temp_cache.drop("schedule-college-index")
    temp_cache.drop("schedule-college-index")          #повтор — не ошибка
    assert temp_cache.load("schedule-college-index") is None


@pytest.fixture
def clean_mimetypes(monkeypatch):
    """Состояние `mimetypes` до первого обращения — и возврат прежнего после теста:
    таблица глобальная, и чужие тесты не должны получить нашу."""
    for name in ("_db", "inited", "types_map", "common_types", "suffix_map", "encodings_map"):
        monkeypatch.setattr(mimetypes, name, getattr(mimetypes, name))
    monkeypatch.setattr(mimetypes, "_gb_fast", False, raising=False)
    monkeypatch.setattr(mimetypes, "_db", None)
    monkeypatch.setattr(mimetypes, "inited", False)


def test_mime_types_come_without_the_windows_registry(monkeypatch, clean_mimetypes):
    def _boom(self, *a, **k):
        raise AssertionError("реестр Windows прочитан — это 0.4–0.6 с на каждом старте")
    monkeypatch.setattr(mimetypes.MimeTypes, "read_windows_registry", _boom, raising=False)
    local_api._fast_mimetypes()
    #Всё, что реально лежит в сборке сайта, — с правильным типом.
    expect = {"a.js": "text/javascript", "a.css": "text/css", "a.html": "text/html",
              "a.svg": "image/svg+xml", "a.png": "image/png", "a.webp": "image/webp",
              "a.woff2": "font/woff2", "a.m4a": "audio/mp4", "a.ogg": "audio/ogg",
              "a.json": "application/json", "a.webmanifest": "application/manifest+json",
              "a.gif": "image/gif", "a.txt": "text/plain", "a.xml": "text/xml"}
    for fname, typ in expect.items():
        assert mimetypes.guess_type(fname)[0] == typ, fname


def test_every_extension_of_the_site_build_has_a_type(clean_mimetypes):
    """Свойство, а не список: новый тип файла в сборке сайта без записи в таблице —
    красный прогон, а не молча `application/octet-stream` в программе."""
    root = os.path.join(os.path.dirname(__file__), "..", "web", "dist")
    if not os.path.isdir(root):
        pytest.skip("сборки сайта нет — проверять нечего (предмет отсутствует)")
    local_api._fast_mimetypes()
    exts = set()
    for _r, _d, files in os.walk(root):
        exts.update(os.path.splitext(f)[1].lower() for f in files if "." in f)
    missing = sorted(e for e in exts if not mimetypes.guess_type("x" + e)[0])
    assert not missing, f"нет типа для {missing} — добавь в local_api._EXTRA_MIME"


def _start_body():
    src = open(local_api.__file__, encoding="utf-8").read()
    return src[src.index("    def start(self) -> bool:"):src.index("    def _load_app(self):")]


def test_schedule_cache_is_installed_before_the_server_starts():
    body = _start_body()
    assert "install_schedule_cache()" in body, "кэш расписания не подключается при старте"
    assert body.index("install_schedule_cache()") < body.index("uvicorn.Server("), \
        "кэш подключается после старта — прогрев в lifespan его не увидит"


def test_fast_mimetypes_runs_before_the_app_is_loaded():
    src = open(local_api.__file__, encoding="utf-8").read()
    prep = src[src.index("    def _prepare_env(self):"):src.index("    def start(self) -> bool:")]
    assert "_fast_mimetypes()" in prep


def test_routes_are_warmed_right_after_the_server_is_ready():
    """Замер: первый запрос мимо /health стоил ~250 мс (FastAPI строит маршруты лениво),
    с прогревом первая страница — 6 мс. Прогрев обязан идти ПОСЛЕ готовности (иначе
    некуда слать) и в ФОНЕ (иначе цена просто переедет в start)."""
    body = _start_body()
    assert "self._warm_routes()" in body, "прогрев маршрутов не вызывается при старте"
    assert body.index("self._wait_ready()") < body.index("self._warm_routes()")
    src = open(local_api.__file__, encoding="utf-8").read()
    warm = src[src.index("    def _warm_routes(self)"):src.index("    def _load_app(self):")]
    assert "threading.Thread(" in warm and ".start()" in warm, "прогрев ждёт ответа в start()"
