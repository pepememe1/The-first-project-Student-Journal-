"""Какое приложение стучится и какой версии: раздел «Сессии» у админа и обязательное обновление.

Заголовок `X-Gb-App` ставит сам клиент: «apk/4.1.5», «exe/4.1.5», «web/4.1.5», после «+» —
метка сборки. Подделать его тривиально, поэтому прав он не даёт: худшее, что даёт
подделка, — просьба обновиться. Нет заголовка (сборки до 4.1.5) — не блокируем никогда.

Блокируются только приложения (apk, exe): сайт всегда свежий, его отдаёт сервер. Порог —
`desktop_update.MAX_RELEASES_BEHIND` выпусков по списку `desktop_update.RELEASES`.
"""
from __future__ import annotations

import desktop_update

PLATFORMS = ("apk", "exe", "web")
BLOCKED_PLATFORMS = ("apk", "exe")
#Без этих адресов обновиться было бы нечем: манифесты, бандлы, файлы, проверка жизни.
EXEMPT_PREFIXES = ("/health", "/app/updates", "/app/bundles", "/app/client-report",
                   "/desktop/updates", "/downloads")


def parse(header: str | None) -> dict | None:
    """«apk/4.1.5+1761234567» → {platform, release, build}; мусор → None."""
    raw = (header or "").strip()[:80]
    if "/" not in raw:
        return None
    platform, _, rest = raw.partition("/")
    release, _, build = rest.partition("+")
    platform = platform.lower()
    if platform not in PLATFORMS or not desktop_update.parse_version(release):
        return None
    return {"platform": platform, "release": release, "build": build[:40]}


def label(header: str | None) -> str:
    """Короткая подпись для таблицы сессий: «apk 4.1.5»; пусто — клиент не назвался."""
    p = parse(header)
    return "%s %s" % (p["platform"], p["release"]) if p else ""


def guess(client: str, user_agent: str) -> str:
    """Подпись для сессий сборок, которые ещё не называли себя заголовком."""
    ua = (user_agent or "").lower()
    if client == "android" or "wv)" in ua or "dalvik" in ua:
        return "apk (до 4.1.5)"
    if not client and ("python" in ua or "httpx" in ua):
        return "exe (до 4.1.5)"
    return "сайт" if ua else ""


def update_required(header: str | None, path: str) -> int:
    """На сколько выпусков отстало приложение, если пора блокировать; иначе 0."""
    if path.startswith(EXEMPT_PREFIXES):
        return 0
    p = parse(header)
    if not p or p["platform"] not in BLOCKED_PLATFORMS:
        return 0
    behind = desktop_update.releases_behind(p["release"])
    return behind if behind >= desktop_update.MAX_RELEASES_BEHIND else 0
