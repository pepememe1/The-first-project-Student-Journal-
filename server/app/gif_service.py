"""
gif_service.py — GIF-пикер мессенджера (Klipy).

━━ ПОЧЕМУ KLIPY, И ПОЧЕМУ ПРОКСИ, А НЕ ПРЯМОЙ ВЫЗОВ С КЛИЕНТА ━━
Ключ — инфраструктурный секрет (как токен RuStore Push), а не выбор ИИ-провайдера,
поэтому живёт в `.env`/config.py, а не в `/web/admin/ai-config`. Все запросы к Klipy
идут ЧЕРЕЗ СЕРВЕР: иначе ключ пришлось бы отдать в браузер/десктоп/мобильное
приложение, и любой клиент мог бы вычерпать общий лимит запросов или использовать
ключ за пределами нашего продукта.

━━ ОТВЕТ KLIPY УРЕЗАЕТСЯ ━━
Их объект GIF — это 5 размеров × 5 форматов + blur_preview в виде base64 (десятки КБ на
каждую картинку). Пикеру нужны ровно два URL (превью для сетки, ссылка для отправки) —
остальное отбрасываем на сервере, а не тащим в браузер списком из 20-30 GIF.

━━ ССЫЛКА В СООБЩЕНИИ — ТОЛЬКО С CDN KLIPY ━━
`is_allowed_url()` проверяет хост ПЕРЕД тем, как ссылка попадёт в Message.body — тот же
принцип белого списка, что у видео-эмбедов мессенджера (SSRF/подмена закрыты
архитектурно, а не проверкой на глаз): без него любой мог бы прислать «GIF-сообщение»
с произвольным URL.

━━ КЭШ КАТЕГОРИЙ ━━
Список категорий у Klipy почти не меняется — TTL-кэш в памяти процесса (тот же приём,
что у esstu_parser для справочника специальностей): открывать пикер не должно стоить
сетевого похода при тестовом лимите 100 запросов/час.

Нет ключа/сеть недоступна → пустые списки, а не исключение: GIF — дополнение к чату,
а не условие его работы (тот же принцип, что у STT/TTS/RuStore push).
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("gradebook.gif")

_BASE = "https://api.klipy.com/api/v1"
TIMEOUT_S = 8
#⚠️ ОБЯЗАТЕЛЕН: Klipy отвечает 403 на дефолтный User-Agent urllib
#(«Python-urllib/x.y») — простейшая защита от ботов на их стороне, не документирована,
#поймано эмпирически при первом же реальном запросе с тестовым ключом.
_UA = "gradebookai-server/1.0"

#Единственный хост, откуда реально можно слать GIF в сообщение.
ALLOWED_CDN_HOST = "static.klipy.com"

_CATEGORIES_CACHE = {"ts": 0.0, "data": []}
_CATEGORIES_TTL = 6 * 3600


def _get(path: str, params: dict) -> dict | None:
    """GET к Klipy. None — не настроено/сеть недоступна/ошибка."""
    if not config.KLIPY_API_KEY:
        return None
    query = urllib.parse.urlencode(
        {k: v for k, v in params.items() if v not in (None, "")})
    url = f"{_BASE}/{config.KLIPY_API_KEY}/{path}"
    if query:
        url += f"?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:      # noqa: BLE001 — сбой GIF-провайдера не роняет чат
        log.warning("Klipy недоступен (%s): %s", path, e)
        return None


def _simplify(item: dict) -> dict:
    files = item.get("file") or {}
    thumb = (files.get("xs") or files.get("sm") or {}).get("webp") or {}
    send = (files.get("md") or files.get("sm") or files.get("hd") or {}).get("gif") or {}
    return {
        "id": item.get("id"),
        "slug": item.get("slug") or "",
        "title": item.get("title") or "",
        "thumb_url": thumb.get("url") or "",
        "url": send.get("url") or "",
        "width": send.get("width") or thumb.get("width") or 0,
        "height": send.get("height") or thumb.get("height") or 0,
    }


def _gif_list(payload: dict | None) -> dict:
    if not payload or not payload.get("result"):
        return {"items": [], "has_next": False}
    data = payload.get("data") or {}
    items = [_simplify(x) for x in (data.get("data") or []) if x.get("slug")]
    return {"items": items, "has_next": bool(data.get("has_next"))}


def trending(page: int = 1, per_page: int = 24) -> dict:
    """{items: [...], has_next}. Пустой список — GIF просто не показываются, чат работает."""
    return _gif_list(_get("gifs/trending", {"page": page, "per_page": per_page}))


def search(query: str, page: int = 1, per_page: int = 24) -> dict:
    query = (query or "").strip()
    if not query:
        return {"items": [], "has_next": False}
    return _gif_list(_get("gifs/search", {"q": query, "page": page, "per_page": per_page}))


def categories() -> list:
    """[{label, query, preview_url}]. TTL-кэш — см. докстринг файла."""
    now = time.time()
    if _CATEGORIES_CACHE["data"] and now - _CATEGORIES_CACHE["ts"] < _CATEGORIES_TTL:
        return _CATEGORIES_CACHE["data"]
    payload = _get("gifs/categories", {})
    if not payload or not payload.get("result"):
        return _CATEGORIES_CACHE["data"]      #старое лучше пустого, если сеть моргнула
    cats = [{"label": c.get("category", ""), "query": c.get("query", ""),
            "preview_url": c.get("preview_url", "")}
           for c in ((payload.get("data") or {}).get("categories") or [])
           if c.get("query")]
    _CATEGORIES_CACHE["data"] = cats
    _CATEGORIES_CACHE["ts"] = now
    return cats


def is_allowed_url(url: str) -> bool:
    """Ссылка, которую сохраняем в Message.body, обязана вести на CDN Klipy.

    ⚠️ ПРЕЖДЕ ЧЕМ ДОПИСАТЬ СЮДА ХОСТ — прочитай docs/PLAN-EXTERNAL-GIFS.md §2.
    Эту функцию зовут ТРИ разных места, и у них разная цена ошибки: тело GIF-сообщения,
    избранное (`me._sanitize_gif_favorites`) и АВАТАРКА С БАННЕРОМ
    (`me._sanitize_profile_media`). Аватарка — публичное поле, его подставляет в
    `<img src>` каждый, кто открыл список чатов: разрешив здесь чужой хост «ради
    гифок», ты заодно дашь одному человеку собирать IP всех, кто на него посмотрел, —
    ровно ту дыру, которую закрывали в 3.7. Расширять надо РАЗДЕЛЕНИЕМ правила на
    широкое (гифки) и узкое (аватарка), а не одним хостом в общий список."""
    try:
        host = urllib.parse.urlparse(url or "").hostname or ""
    except Exception:
        return False
    return host == ALLOWED_CDN_HOST


def mark_shared(slug: str) -> None:
    """Сообщает Klipy, что GIF реально ОТПРАВЛЕН (их собственная статистика показов —
    часть условий использования API, не наша аналитика). Best-effort: сбой не мешает
    уже созданному сообщению — зовётся ПОСЛЕ commit, не до."""
    if not config.KLIPY_API_KEY or not slug:
        return
    url = f"{_BASE}/{config.KLIPY_API_KEY}/gifs/{urllib.parse.quote(slug, safe='')}/share"
    req = urllib.request.Request(url, data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": _UA})
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT_S)
    except Exception as e:      # noqa: BLE001
        log.warning("Klipy share-уведомление не удалось (%s): %s", slug, e)


def invalidate_categories_cache() -> None:
    """Для тестов — сбросить TTL-кэш категорий между прогонами."""
    _CATEGORIES_CACHE["ts"] = 0.0
    _CATEGORIES_CACHE["data"] = []
