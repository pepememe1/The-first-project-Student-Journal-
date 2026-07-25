"""
avatar_service.py — аватарка пользователя (десктоп).

Хранение как у темы (theme_service): картинка (обрезанная 256×256 JPEG в виде data:URL)
лежит в prefs.avatar — роумится между устройствами через /me/prefs + синк и СОВМЕСТИМА с
вебом (там та же prefs.avatar). Плюс локальный кэш этого аккаунта на ПК — мгновенно и
офлайн. Приоритет чтения: локальный кэш → синхронизированная запись пользователя → ''.
"""
import log
from data_store import get_store, local_get, local_set

_LOCAL_PREFIX = "my_avatar"


def _ident_token(role: str, identity: dict) -> str:
    """Стабильный токен аккаунта (тот же принцип, что в theme_service — не путать акки на
    общем ПК колледжа)."""
    identity = identity or {}
    if role == "teacher":
        return "teacher:" + (identity.get("name", "") or "?")
    if role == "student":
        return "student:{}|{}|{}".format(identity.get("f", ""), identity.get("n", ""),
                                         identity.get("g", ""))
    if role == "admin":
        return "admin"
    return "default"


def _key(role: str, identity: dict) -> str:
    return f"{_LOCAL_PREFIX}:{_ident_token(role, identity)}"


def _synced_pref(role: str, identity: dict, field: str) -> str:
    """Поле prefs из синхронизированной записи пользователя (роуминг с другого ПК)."""
    identity = identity or {}
    try:
        store = get_store()
        if role == "teacher":
            rec = store.get_teachers().get(identity.get("name", ""), {})
            return (rec.get("prefs") or {}).get(field, "") or ""
        if role == "student":
            f, n, g = identity.get("f", ""), identity.get("n", ""), identity.get("g", "")
            for s in store.get_students():
                if (s.get("surname", "") == f and s.get("name", "") == n
                        and s.get("group", "") == g):
                    return (s.get("prefs") or {}).get(field, "") or ""
    except Exception:
        pass
    return ""


def _synced_avatar(role: str, identity: dict) -> str:
    """avatar из синхронизированной записи пользователя (для роуминга с другого ПК)."""
    return _synced_pref(role, identity, "avatar")


def get_avatar(role: str, identity: dict = None) -> str:
    """Текущая аватарка аккаунта (data:URL) или ''. Локальный кэш → синк-запись → пусто."""
    identity = identity or {}
    cached = local_get(_key(role, identity), None)
    if isinstance(cached, str) and cached:
        return cached
    return _synced_avatar(role, identity)


def save_avatar(data_url: str, role: str, identity: dict = None) -> None:
    """Сохранить аватарку: локальный кэш (мгновенно) + prefs на сервер (роуминг). ''
    (пустая строка) — удалить. Как save_user_theme, self-scope через /me/prefs."""
    identity = identity or {}
    data_url = data_url or ""
    local_set(_key(role, identity), data_url)
    try:
        import sync_runner
        sync_runner.push_my_prefs({"avatar": data_url})
    except Exception as e:
        log.get("avatar_service").warning(f"[avatar] отправка в prefs пропущена: {e}")


# ── Публичная часть профиля: «О себе» и цвет плашки ──────────────────────────────────
# Те же поля, что на вебе (prefs.bio / prefs.profile_color), — профиль общий для платформ.
BIO_LIMIT = 400          #совпадает с лимитом сервера (routers/me.py) и веба


def get_bio(role: str, identity: dict = None) -> str:
    """«О себе» аккаунта. Локальный кэш → синхронизированная запись → пусто."""
    identity = identity or {}
    cached = local_get(f"my_bio:{_ident_token(role, identity)}", None)
    if isinstance(cached, str) and cached:
        return cached
    return _synced_pref(role, identity, "bio")


def get_profile_color(role: str, identity: dict = None) -> str:
    """id пресета палитры для плашки профиля ('' — стандартный акцент)."""
    identity = identity or {}
    cached = local_get(f"my_profile_color:{_ident_token(role, identity)}", None)
    if isinstance(cached, str) and cached:
        return cached
    return _synced_pref(role, identity, "profile_color")


def save_profile(role: str, identity: dict = None, bio: str = None, color: str = None) -> None:
    """Сохранить публичный профиль: локальный кэш + prefs на сервер (роуминг, тот же
    формат, что на вебе). Передавайте только те поля, которые меняете."""
    identity = identity or {}
    payload = {}
    if bio is not None:
        bio = (bio or "").strip()[:BIO_LIMIT]
        local_set(f"my_bio:{_ident_token(role, identity)}", bio)
        payload["bio"] = bio
    if color is not None:
        color = (color or "").strip()[:32]
        local_set(f"my_profile_color:{_ident_token(role, identity)}", color)
        payload["profile_color"] = color
    if not payload:
        return
    try:
        import sync_runner
        sync_runner.push_my_prefs(payload)
    except Exception as e:
        log.get("avatar_service").warning(f"[profile] отправка в prefs пропущена: {e}")
