"""
updater.py — КЛИЕНТСКАЯ часть автообновления десктопа (скачать → проверить → подменить).

Правила формата (какая версия новее, как зовётся патч, чем считается хеш) живут в общем
корневом `desktop_update.py` — том же, что использует сборщик патчей и сервер. Здесь
только то, что бывает ТОЛЬКО на компьютере пользователя: сеть, диск и подмена .exe.

── Как это работает ──────────────────────────────────────────────────────────────────
1. `check_and_fetch()` (фоновый поток при старте) берёт `<сервер>/desktop/updates`,
   сравнивает с `APP_VERSION` и, если есть что ставить, качает ДЕЛЬТУ (обычно единицы
   МБ) либо, если дельты нет, .exe целиком.
2. Собранный новый .exe кладётся РЯДОМ как `GradeBookAI.new.exe` и проверяется по
   SHA-256 из манифеста. Не сошёлся — файл удаляется, обновление не состоится.
3. `apply_pending()` (в самом начале следующего запуска, ДО открытия окна) подменяет
   файлы и просит перезапуск.

⚠️ **Почему подмена именно переименованием.** Windows не даёт ПЕРЕЗАПИСАТЬ запущенный
.exe, но спокойно даёт его ПЕРЕИМЕНОВАТЬ. Поэтому: текущий → `.old`, новый → на место
текущего. Уборка `.old` — на следующем запуске (пока процесс жив, файл занят).

⚠️ **Обновление НИКОГДА не выполняется молча в момент работы.** Человек может вести
журнал; подмена файла под работающей программой — это как минимум неожиданный
перезапуск. Скачиваем в фоне, ставим на старте.
"""
import os
import json
import shutil
import tempfile
import threading
import urllib.request
import urllib.error

import log
import app_paths
import desktop_update as DU

#Модуль log отдаёт логгер через get(), прямых info/warn у него нет.
_LOG = log.get("updater")

EXE_NAME = "GradeBookAI.exe"
NEW_SUFFIX = ".new.exe"
OLD_SUFFIX = ".old.exe"
#Метка рядом с новым файлом: какая версия скачана и какой у неё хеш. Без неё после
#перезапуска нечем отличить готовое к установке обновление от мусора, оставшегося от
#оборванной закачки.
PENDING_NAME = "pending_update.json"

_TIMEOUT = 30           #секунд на запрос: обновление не должно подвешивать запуск
_MAX_EXE_BYTES = 300 * 1024 * 1024   #потолок здравого смысла (.exe ~48 МБ)


def _exe_path() -> str:
    """Путь к САМОМУ .exe программы (не к временной распаковке onefile).

    ⚠️ `sys.executable` НЕ годится под Nuitka onefile (единственный релизный сборщик,
    §8.1 CLAUDE.md) — он указывает на временный bootstrap-интерпретатор в %TEMP%, а
    не на настоящий .exe (см. app_paths.py::_nuitka_onefile_dir, там же разбор живого
    бага «автообновление не работает»: апдейтер молча подменял файл не там). Берём
    ИМЯ файла из EXE_NAME и ПАПКУ из app_paths.app_dir() — она уже учитывает разницу
    PyInstaller/Nuitka сама, второй копии этой логики здесь не нужно."""
    return os.path.join(app_paths.app_dir(), EXE_NAME)


def _pending_path() -> str:
    return os.path.join(app_paths.data_dir(), PENDING_NAME)


def _new_exe_path() -> str:
    return _exe_path() + NEW_SUFFIX


def _old_exe_path() -> str:
    return _exe_path() + OLD_SUFFIX


def _get(url: str, timeout: int = _TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "GradeBookAI-updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_manifest(base_url: str) -> dict:
    """Манифест обновлений или {} (нет сети/нет обновлений — это НЕ ошибка)."""
    base = (base_url or "").rstrip("/")
    if not base:
        return {}
    try:
        return json.loads(_get(f"{base}/desktop/updates").decode("utf-8"))
    except Exception as e:                                   # noqa: BLE001
        _LOG.info(f"[update] манифест недоступен: {e}")
        return {}


def _download(url: str, dest: str, expect_sha: str) -> bool:
    """Качает во ВРЕМЕННЫЙ файл рядом и переименовывает только после проверки хеша.

    Скачивание прямо в целевой файл оставило бы после обрыва связи полуфайл, который
    выглядит как готовое обновление."""
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GradeBookAI-updater/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r, open(tmp, "wb") as f:
            total = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_EXE_BYTES:
                    raise ValueError("файл обновления неправдоподобно велик")
                f.write(chunk)
        got = DU.sha256_file(tmp)
        if expect_sha and got != expect_sha:
            _LOG.warning(f"[update] хеш не сошёлся: ждали {expect_sha[:12]}…, получили {got[:12]}…")
            return False
        os.replace(tmp, dest)
        return True
    except Exception as e:                                   # noqa: BLE001
        _LOG.warning(f"[update] не удалось скачать {url}: {e}")
        return False
    finally:
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _apply_patch(old_exe: str, patch_file: str, out_exe: str) -> bool:
    """Накладывает дельту на текущий .exe (zstd, старый файл как словарь).

    zstandard импортируется ЛЕНИВО и только здесь: без патча (полная закачка) он не
    нужен вовсе, и сборка без него остаётся рабочей — просто обновления пойдут целиком.
    """
    try:
        import zstandard
    except ImportError:
        _LOG.info("[update] zstandard недоступен — дельту не применить, качаем целиком")
        return False
    try:
        with open(old_exe, "rb") as f:
            base = f.read()
        with open(patch_file, "rb") as f:
            patch = f.read()
        dctx = zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(base))
        data = dctx.decompress(patch, max_output_size=_MAX_EXE_BYTES)
        with open(out_exe, "wb") as f:
            f.write(data)
        return True
    except Exception as e:                                   # noqa: BLE001
        _LOG.warning(f"[update] патч не наложился: {e}")
        return False


def check_and_fetch(base_url: str, current_version: str) -> dict:
    """Проверить, скачать и подготовить обновление. Возвращает {} либо {version, path}.

    Ничего не подменяет — только кладёт готовый .exe рядом и пишет метку. Установка —
    `apply_pending()` на следующем запуске.
    """
    man = fetch_manifest(base_url)
    if not DU.has_update(man, current_version):
        return {}
    latest = DU.normalize(man.get("version") or "")
    base = (base_url or "").rstrip("/")
    new_exe = _new_exe_path()
    #Уже скачано это же обновление — второй раз не тянем (частый случай: человек
    #закрыл программу до перезапуска).
    done = read_pending()
    if done.get("version") == latest and os.path.isfile(new_exe):
        return done

    patch = DU.pick_patch(man, current_version)
    ok = False
    if patch:
        tmp_patch = os.path.join(tempfile.gettempdir(), patch["file"])
        if _download(f"{base}/downloads/{DU.UPDATES_DIR_NAME}/{patch['file']}",
                     tmp_patch, patch.get("sha256", "")):
            ok = _apply_patch(_exe_path(), tmp_patch, new_exe)
            if ok and DU.sha256_file(new_exe) != patch.get("target_sha256"):
                #Патч лёг «успешно», но результат не тот — чаще всего это значит, что
                #обновляемся не с той сборки, для которой патч собран.
                _LOG.warning("[update] результат патча не совпал с ожидаемым — качаю целиком")
                os.remove(new_exe)
                ok = False
            try:
                os.remove(tmp_patch)
            except OSError:
                pass

    if not ok:
        full = man.get("full") or {}
        if not full.get("file"):
            return {}
        ok = _download(f"{base}/downloads/{DU.UPDATES_DIR_NAME}/{full['file']}",
                       new_exe, full.get("sha256", ""))
    if not ok:
        return {}

    info = {"version": latest, "path": new_exe, "sha256": DU.sha256_file(new_exe)}
    _write_pending(info)
    _LOG.info(f"[update] обновление {latest} готово, установится при следующем запуске")
    return info


def read_pending() -> dict:
    try:
        with open(_pending_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:                                        # noqa: BLE001
        return {}


def _write_pending(info: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_pending_path()), exist_ok=True)
        with open(_pending_path(), "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False)
    except OSError as e:
        _LOG.warning(f"[update] не удалось записать метку обновления: {e}")


def clear_pending() -> None:
    for p in (_pending_path(), _new_exe_path()):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def cleanup_old() -> None:
    """Убирает `.old.exe` от прошлой установки. Занят — молча оставляем до следующего раза."""
    old = _old_exe_path()
    if os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass


def apply_pending(current_version: str) -> bool:
    """Установить скачанное обновление. True — файл подменён, нужен перезапуск.

    Зовётся В САМОМ НАЧАЛЕ запуска, до открытия окна: подменять .exe под работающей
    программой нельзя, а на старте процесс ещё не начал ничего показывать человеку.
    """
    cleanup_old()
    info = read_pending()
    new_exe = _new_exe_path()
    if not info or not os.path.isfile(new_exe):
        return False
    #Уже стоит эта версия (или новее) — метка протухла, чистим.
    if not DU.is_newer(info.get("version") or "", current_version):
        clear_pending()
        return False
    #Файл мог быть повреждён после скачивания (диск, антивирус) — проверяем ещё раз
    #ПЕРЕД подменой: это последняя точка, где отказ ничего не стоит.
    if info.get("sha256") and DU.sha256_file(new_exe) != info["sha256"]:
        _LOG.warning("[update] скачанный файл повреждён — обновление отменено")
        clear_pending()
        return False

    cur, old = _exe_path(), _old_exe_path()
    try:
        if os.path.isfile(cur):
            os.replace(cur, old)          #переименовать запущенный .exe Windows разрешает
        os.replace(new_exe, cur)
    except OSError as e:
        _LOG.warning(f"[update] не удалось подменить файл программы: {e}")
        #Откатываемся, чтобы не остаться вообще без .exe.
        try:
            if not os.path.isfile(cur) and os.path.isfile(old):
                os.replace(old, cur)
        except OSError:
            pass
        return False
    try:
        os.remove(_pending_path())
    except OSError:
        pass
    _LOG.info(f"[update] установлена версия {info.get('version')}")
    return True


def start_background_check(base_url: str, current_version: str) -> None:
    """Фоновая проверка обновлений — daemon-поток, чтобы не задерживать запуск и выход."""
    def _run():
        try:
            check_and_fetch(base_url, current_version)
        except Exception as e:                               # noqa: BLE001
            _LOG.info(f"[update] фоновая проверка не удалась: {e}")
    threading.Thread(target=_run, name="updater", daemon=True).start()
