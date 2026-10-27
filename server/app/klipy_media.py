"""Гифки Klipy — с нашего домена, а не с CDN Klipy (27.10.2026, требование Влада).

🔥 ЗАЧЕМ. `static.klipy.com` из России открывается не у всех: без VPN гифки в чатах,
аватарки и баннеры профиля были пустыми. Наш сервер до Klipy доходит (проверено с боя
27.10.2026: CDN отвечает 200 за 0,23 с), поэтому браузер берёт файл у нас:
`/media/klipy/<путь на CDN>`. Первый запрос сервер скачивает и кладёт на диск, следующие
отдаёт уже с диска — а на бою их отдаёт сам Caddy, не будя Python (`server/Caddyfile`,
блок `@klipy_cached`): процесс приложения ОДИН на одном ядре, и раздавать им файлы —
значит отнимать время у журнала (тот же довод, что у вложений, §5.4).

Попутно Klipy перестаёт видеть адреса студентов: раньше каждый показ гифки был запросом
браузера студента к иностранному CDN (`docs/security/SUBPROCESSORS.md`).

⚠️ ЭТО НЕ ОТКРЫТЫЙ ПРОКСИ. Хост один и зашит (`static.klipy.com`), путь — по строгому
шаблону с расширением картинки или ролика, размер ограничен, промахи кэша — под
ограничителем частоты на адрес. Подставить чужой сайт нечем: в адресе есть только путь.

⚠️ ПЕРВЫЙ КАДР — ЗАПАСНОЙ ПУТЬ. У каждой гифки Klipy по тому же адресу лежит неподвижный
`.webp` (первый кадр). Поставил человек гифку на аватарку или баннер — сервер сразу
скачивает её кадр и ролик (`pin`), и они не вытесняются из кэша, пока на них ссылается
профиль. Klipy потом недоступен даже нам — аватарка остаётся кадром, а не пустым кругом.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, events, shared_state

KLIPY_HOST = "static.klipy.com"
PREFIX = "/media/klipy/"
#Путь на CDN: каталоги из букв, цифр, `_`, `-`, точек; файл — картинка или ролик.
#Без `..`, без двойных слэшей, без запроса — сверяется ДО любого похода в сеть.
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.]*(?:/[A-Za-z0-9][A-Za-z0-9_\-.]*){0,8}"
                      r"\.(gif|webp|mp4|jpg|jpeg|png)$", re.IGNORECASE)
MIME = {"gif": "image/gif", "webp": "image/webp", "mp4": "video/mp4", "jpg": "image/jpeg",
        "jpeg": "image/jpeg", "png": "image/png"}
#Один файл: ролики аватарок — десятки КБ, но гифки бывают и по 15 МБ (`mediaSrc.js`).
MAX_FILE_BYTES = 20 * 1024 * 1024
FETCH_TIMEOUT_S = 15
#Промахов кэша на адрес за 10 минут. Попадания (файл уже на диске) не считаются: их на
#бою отдаёт Caddy, а здесь — дешёвое чтение с диска. Предел щедрый намеренно: колледж
#сидит за ОДНИМ адресом (NAT), и это общий счёт всех, кто листает гифки в аудиториях.
MISSES_PER_WINDOW = 1500
_WINDOW_S = 600
_UA = "gradebookai-server/1.0"
_K_MISS = "klipy:miss:"
_K_SWEEP = "klipy:sweep"
_K_WRITTEN = "klipy:written"


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """Переадресацию CDN принимаем только на тот же хост: иначе открытая переадресация
    на стороне Klipy превратила бы нашу ручку в прокси к любому адресу (Полковник,
    28.10.2026). Проверка типа ответа здесь не защита — картинку отдаёт кто угодно."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme != "https" or u.hostname != KLIPY_HOST or u.port or u.username:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def cache_dir() -> Path:
    """Каталог кэша. На бою — `GRADEBOOK_KLIPY_CACHE_DIR` (его же читает Caddy, поэтому
    НЕ под `/root`: у пользователя `caddy` туда нет доступа, см. шапку Caddyfile)."""
    env = (os.environ.get("GRADEBOOK_KLIPY_CACHE_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "klipy_cache"


def cache_limit_bytes() -> int:
    try:
        mb = int(os.environ.get("GRADEBOOK_KLIPY_CACHE_MB") or 300)
    except ValueError:
        mb = 300
    return max(mb, 16) * 1024 * 1024


def path_of_url(url: str) -> str:
    """Путь на CDN из ссылки Klipy ('' — ссылка не Klipy или путь не по шаблону)."""
    try:
        u = urllib.parse.urlparse(url or "")
    except ValueError:
        return ""
    if u.scheme != "https" or u.hostname != KLIPY_HOST or u.port or u.username or u.query:
        return ""
    path = u.path.lstrip("/")
    return path if path_ok(path) else ""


def path_ok(path: str) -> bool:
    return bool(path) and ".." not in path and bool(_PATH_RE.match(path))


def mime_of(path: str) -> str:
    return MIME.get(path.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def local_file(path: str) -> Path:
    """Где лежит файл кэша. Путь уже проверен `path_ok` — за каталог он не выйдет."""
    return cache_dir() / path


def cached(path: str):
    f = local_file(path)
    return f if f.is_file() else None


def _download(path: str) -> bytes:
    req = urllib.request.Request(f"https://{KLIPY_HOST}/{path}",
                                 headers={"User-Agent": _UA, "Accept": "*/*"})
    opener = urllib.request.build_opener(_SameHostRedirect)
    with opener.open(req, timeout=FETCH_TIMEOUT_S) as r:      # noqa: S310
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not (ctype.startswith("image/") or ctype == "video/mp4"):
            raise ValueError(f"CDN отдал не картинку: {ctype or 'без типа'}")
        body = r.read(MAX_FILE_BYTES + 1)
    if len(body) > MAX_FILE_BYTES:
        raise ValueError("файл больше предела")
    if not body:
        raise ValueError("пустой ответ CDN")
    return body


def _store(path: str, body: bytes) -> Path:
    """Записать атомарно: Caddy не должен увидеть недописанный файл."""
    target = local_file(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o644)              #читает Caddy — другой пользователь
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def miss_allowed(ip: str) -> bool:
    """Ограничитель промахов кэша на адрес — общая дверь `shared_state`."""
    key = _K_MISS + (ip or "-")
    if shared_state.window_count(key, _WINDOW_S) >= MISSES_PER_WINDOW:
        return False
    shared_state.window_add(key, _WINDOW_S)
    return True


def fetch(path: str):
    """Файл из кэша, а при промахе — скачанный с CDN. None — получить не удалось."""
    f = cached(path)
    if f is not None:
        return f
    #Выключатель Klipy один на всё — пустой ключ (`docs/security/SUBPROCESSORS.md`): на
    #отказ ВСГУТУ гасится и поиск, и скачивание файлов, а не только панель GIF.
    if not config.KLIPY_API_KEY:
        return None
    try:
        body = _download(path)
        f = _store(path, body)
        _count_written(len(body))
        return f
    except Exception as e:      # noqa: BLE001
        #Не тревога: гифку удалили на CDN или он недоступен — клиент покажет кадр или
        #значок. Но след нужен: «гифки пропали у всех» иначе не отличить от одной битой.
        events.record("warn", "klipy_fetch_failed",
                      f"гифка Klipy не получена: {type(e).__name__}: {e}"[:300], "", "")
        return None


def variants(path: str) -> list:
    """Что держать про запас для гифки-аватарки: первый кадр, ролик, сама гифка."""
    if not path.lower().endswith(".gif"):
        return [path]
    stem = path[:-4]
    return [stem + ".webp", stem + ".mp4", path]


def pin(url: str) -> None:
    """Скачать про запас кадр и ролик гифки, которую поставили на аватарку или баннер.

    В фоне: человек сохраняет профиль и ждать CDN не должен. Сбой — не ошибка: тогда
    файл скачается при первом показе."""
    path = path_of_url(url)
    if not path:
        return

    def _worker():
        for p in variants(path):
            if cached(p) is None:
                fetch(p)

    threading.Thread(target=_worker, daemon=True).start()


def sweep(protected: set, now: float = 0.0) -> int:
    """Удержать кэш в пределе: удалить самые старые файлы, кроме тех, на которые
    ссылаются профили и беседы (`protected` — пути). Возвращает, сколько удалено.

    ⚠️ «Старые» — по времени записи: попадания на бою отдаёт Caddy и время доступа не
    трогает, поэтому LRU здесь честно не построить. Аватарки и баннеры защищены явно,
    остальное — гифки переписки, которые при нужде скачаются снова."""
    root = cache_dir()
    if not root.is_dir():
        return 0
    files = []
    total = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            full = Path(dirpath) / name
            try:
                st = full.stat()
            except OSError:
                continue
            rel = full.relative_to(root).as_posix()
            if name.startswith(".part-") and (now or time.time()) - st.st_mtime > 3600:
                full.unlink(missing_ok=True)          #обрывок записи, переживший сбой
                continue
            total += st.st_size
            files.append((st.st_mtime, st.st_size, full, rel))
    limit = cache_limit_bytes()
    if total <= limit:
        return 0
    target = int(limit * 0.8)
    removed = 0
    for _mt, size, full, rel in sorted(files):
        if total <= target:
            break
        if rel in protected:
            continue
        try:
            full.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    return removed


def _count_written(size: int) -> None:
    shared_state.update(_K_WRITTEN, lambda cur: int(cur or 0) + int(size), ttl=86400)


def sweep_due() -> bool:
    """Пора ли убирать кэш.

    Раз в 10 минут — и ВНЕ очереди, если с прошлой уборки записано больше пятой части
    предела: иначе поток промахов (до 1500 файлов по 20 МБ за окно с одного адреса) успел
    бы занять диск задолго до плановой уборки, а диск боя — общий с базой и её копиями
    (нашёл Полковник 28.10.2026). Решает ровно один процесс (`claim` / `take`)."""
    written = int(shared_state.get(_K_WRITTEN) or 0)
    if written >= cache_limit_bytes() // 5 and shared_state.take(_K_WRITTEN) is not None:
        return True
    if shared_state.claim(_K_SWEEP, 600):
        shared_state.delete(_K_WRITTEN)
        return True
    return False


def protected_paths(db) -> set:
    """Пути, на которые ссылаются профили и картинки бесед: их не вытеснять никогда."""
    from .models import Conversation, User
    out = set()
    for (prefs,) in db.query(User.prefs).filter(User.deleted == False).all():  # noqa: E712
        if isinstance(prefs, dict):
            for key in ("avatar", "profile_banner"):
                for p in variants(path_of_url(str(prefs.get(key) or ""))):
                    if p:
                        out.add(p)
    for (avatar,) in db.query(Conversation.avatar).filter(Conversation.avatar.like(
            f"https://{KLIPY_HOST}/%")).all():
        for p in variants(path_of_url(avatar or "")):
            if p:
                out.add(p)
    return out
