# -*- coding: utf-8 -*-
"""
test_caddyfile.py — 🔒 БОЕВОЙ КОНФИГ CADDY ПОД ТЕСТОМ.

━━ ЗАЧЕМ ━━
`server/Caddyfile` был ЕДИНСТВЕННЫМ файлом продукта без единой проверки, и это уже стоило
прод-бага: CSP резал картинки Klipy, и увидеть это можно было только живым запросом после
выкладки. Цена ошибки здесь высокая и несимметричная — файл стоит на входе у ВСЕГО
продукта, а его правки доезжают до людей без прогона тестов вообще.

━━ ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, А ЧТО НЕТ ━━
Синтаксис Caddy мы не разбираем: для этого нужен сам Caddy, а тащить его в CI ради
подсветки фигурных скобок незачем. Проверяются УТВЕРЖДЕНИЯ, каждое из которых уже
ломалось или было бы дорого сломать:

  • security-заголовки на месте и с нужными значениями;
  • CSP не разрешает лишнего (внешние CDN шрифтов, `unsafe-eval`, `*` в script-src);
  • сжатие включено — его не было НИКОГДА, и главный бандл уезжал без единого байта
    сжатия (1 355 396 → 286 658 байт после правки);
  • статика раздаётся НЕ из /root (Caddy работает под своим пользователем, а /root имеет
    права 700 — «правильный» по всем примерам из интернета путь даёт 403 на каждый ассет);
  • на приложение пересылается ВСЁ, кроме статики, а не белый список путей: забытый путь
    в белом списке — это не «медленно», это 404 на входе в журнал.

⚠️ Тест читает ФАЙЛ, а не живой сервер: на бою конфиг может отличаться, и это отдельный
риск (правка «руками на машине» переживёт деплой ровно до следующего). Здесь проверяется
то, что мы кладём в git.
"""
import os
import re

import pytest

CADDYFILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "Caddyfile")


@pytest.fixture(scope="module")
def conf() -> str:
    assert os.path.exists(CADDYFILE), "server/Caddyfile пропал — на бою он и есть вход"
    with open(CADDYFILE, encoding="utf-8") as fh:
        return fh.read()


def _uncommented(conf: str) -> str:
    """Конфиг без комментариев. В нём десятки пояснений, и половина упоминает то, что
    когда-то было убрано (Google Fonts, `root /root/...`) — искать по сырому тексту
    значит проверять комментарии вместо директив."""
    return "\n".join(ln for ln in conf.splitlines() if not ln.strip().startswith("#"))


# ── Заголовки ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("header, must_contain", [
    ("Strict-Transport-Security", "max-age="),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=()"),
    ("Content-Security-Policy", "default-src 'self'"),
])
def test_security_header_is_present(conf, header, must_contain):
    """Каждый заголовок задан и несёт ожидаемое значение.

    Обратный ход: убрать любую строку из блока `header` — краснеет свой случай."""
    body = _uncommented(conf)
    line = next((ln for ln in body.splitlines() if ln.strip().startswith(header)), None)
    assert line, f"заголовок {header} пропал из Caddyfile"
    assert must_contain in line, f"{header} потерял «{must_contain}»: {line.strip()}"


def test_hsts_is_at_least_a_year(conf):
    """HSTS короче года не принимается в preload-список браузеров, то есть теряет смысл."""
    m = re.search(r"Strict-Transport-Security\s+\"max-age=(\d+)", _uncommented(conf))
    assert m, "HSTS без max-age"
    assert int(m.group(1)) >= 31536000, "HSTS короче года — preload не примут"


def test_microphone_is_allowed_on_purpose(conf):
    """Микрофон НЕ запрещаем: на нём голосовой ввод Вектора. Запрет убил бы работающую
    функцию молча — браузер просто перестал бы отдавать поток, без ошибки в консоли."""
    m = re.search(r"Permissions-Policy\s+\"([^\"]+)\"", _uncommented(conf))
    assert m, "Permissions-Policy пропал"
    assert "microphone=(self)" in m.group(1), (
        "микрофон запрещён политикой — голосовой ввод перестанет работать")


# ── CSP: что она НЕ должна разрешать ───────────────────────────────────────────────
def _csp(conf: str) -> str:
    m = re.search(r"Content-Security-Policy\s+\"([^\"]+)\"", _uncommented(conf))
    assert m, "CSP пропала из Caddyfile"
    return m.group(1)


@pytest.mark.parametrize("forbidden, why", [
    ("unsafe-eval", "eval открывает исполнение произвольного кода из строки"),
    ("fonts.googleapis.com", "шрифты свои с 3.6; внешний хост — лишний источник и утечка IP (152-ФЗ)"),
    ("fonts.gstatic.com", "то же самое, вторая половина той же ссылки"),
    ("script-src *", "звёздочка в script-src отменяет всю политику"),
    ("default-src *", "звёздочка в default-src отменяет всю политику"),
])
def test_csp_does_not_allow(conf, forbidden, why):
    assert forbidden not in _csp(conf), f"CSP разрешает «{forbidden}»: {why}"


def test_csp_locks_the_dangerous_directives(conf):
    """Три директивы, каждая из которых закрывает свой класс атак целиком."""
    csp = _csp(conf)
    for directive in ("frame-ancestors 'none'", "object-src 'none'", "base-uri 'self'"):
        assert directive in csp, f"CSP потеряла {directive}"


def test_csp_video_hosts_are_a_whitelist(conf):
    """`frame-src` перечисляет хосты поимённо. Открытый `frame-src https:` пустил бы в
    страницу любой сайт — а это и есть встраивание чужого содержимого в журнал."""
    csp = _csp(conf)
    m = re.search(r"frame-src ([^;]+)", csp)
    assert m, "frame-src пропал — видео в мессенджере перестанет открываться"
    hosts = m.group(1).split()
    assert hosts and all(h.startswith("https://") for h in hosts), (
        f"frame-src содержит не-хост: {hosts}")


# ── Сжатие и раздача ───────────────────────────────────────────────────────────────
def test_compression_is_enabled(conf):
    """🔥 Директивы `encode` не было НИКОГДА, и этого не замечали годами: главный бандл
    (1 355 396 байт) уезжал без единого байта сжатия даже когда браузер прямо просил.
    После правки — 286 658 байт zstd, в 4.7 раза меньше."""
    body = _uncommented(conf)
    m = re.search(r"^\s*encode\s+(.+?)\s*\{", body, re.M)
    assert m, "сжатие выключено — сайт снова начнёт отдавать мегабайтные бандлы как есть"
    assert "zstd" in m.group(1) and "gzip" in m.group(1), (
        f"нужны оба кодека (zstd для новых браузеров, gzip для остальных): {m.group(1)}")


def test_static_is_not_served_from_root_home(conf):
    """🔥 МИНА ДЛЯ СЛЕДУЮЩЕГО. Caddy работает под пользователем `caddy`, а /root имеет
    права 700. Прописать `root * /root/gb-deploy/webdist` (ровно так советуют все примеры
    в интернете, потому что деплой лежит там) — значит получить 403 НА КАЖДЫЙ АССЕТ.
    Статика лежит копией в /var/www/gradebook, её кладёт deploy/deploy-web.sh."""
    body = _uncommented(conf)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("root ") and "/root/" in stripped:
            pytest.fail(f"раздача из /root — Caddy получит 403 на каждый файл: {stripped}")


def test_everything_but_static_goes_to_the_app(conf):
    """Пересылаем на приложение ВСЁ, кроме статики, а не белый список путей.

    У продукта есть /auth/*, /me/*, /connect/*, /app/*, /downloads/*, /desktop/updates,
    /public/schedule*, /health и SPA-заглушка. Забытый путь в белом списке — это не
    «медленно», это 404 на входе в журнал."""
    body = _uncommented(conf)
    #Безусловный handle (без матчера) с reverse_proxy внутри — и есть «всё остальное».
    assert re.search(r"^\s*handle\s*\{", body, re.M), (
        "исчез безусловный handle: пересылка стала белым списком путей, и первый забытый "
        "путь отдаст 404 вместо журнала")
    assert re.search(r"reverse_proxy\s+127\.0\.0\.1:8000", body), (
        "приложение больше не за прокси — проверьте порт")


def test_hashed_assets_are_cached_immutably(conf):
    """Ассеты с хешем в имени кэшируются надолго. `Cache-Control` не было вовсе, и
    браузер переспрашивал их каждую загрузку."""
    body = _uncommented(conf)
    assert "immutable" in body, "исчез immutable-кэш для хешированных ассетов"
