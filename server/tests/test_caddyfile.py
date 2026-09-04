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


# ═══════════════════════════════════════════════════════════════════════════════════
# ЧАСТЬ 2 — дописано 03.09.2026.
#
# Первая часть покрыла заголовки, CSP, сжатие и адресацию. Но в конфиге осталась
# половина, за которой стоят настоящие решения, и ни одно из них не было под сторожем:
# защита от slowloris, лимит тела запроса, ротация журнала, предсжатая статика,
# срок жизни кэша у арта пасхалок и реальный IP клиента для анти-брутфорса. Каждое из
# них ломается ОДНОЙ строкой, и ни одна поломка не видна снаружи сразу.
#
# ⚠️ ФОРМА ЗАПИСИ ЗДЕСЬ ДРУГАЯ, И ЭТО НАМЕРЕННО. Проверки вынесены в функции
# `_check_*(conf)`, принимающие ТЕКСТ. Тогда обратный ход не пишется отдельно и не
# повторяет формулу у себя (грабля «тест сверяет копию с копией» из CLAUDE.md):
# прямой тест зовёт функцию на боевом файле, обратный — на нарочно испорченном, и
# сломать защиту можно только правкой обеих половин разом.
# ═══════════════════════════════════════════════════════════════════════════════════


# ── Слоулорис и лимиты тела ────────────────────────────────────────────────────────
def _check_read_header_timeout(conf: str) -> None:
    """Главный рубеж против slowloris: заголовки живой браузер шлёт мгновенно, а
    атакующий тянет их по байту и не заканчивает никогда. Таймаутов здесь не было
    ВООБЩЕ — несколько тысяч таких соединений съедают дескрипторы одноядерной машины,
    не потратив у атакующего почти ничего."""
    m = re.search(r"read_header\s+(\d+)([sm])", _uncommented(conf))
    assert m, "read_header пропал — вернулась беззащитность к slowloris"
    seconds = int(m.group(1)) * (60 if m.group(2) == "m" else 1)
    assert seconds <= 60, (
        "read_header %s — слишком щедро: рубеж должен резать медленные заголовки, "
        "а не ждать их минутами" % m.group(0))


def _check_write_timeout_is_absent(conf: str) -> None:
    """🔥 ОТСУТСТВИЕ ТАЙМАУТА — ТОЖЕ РЕШЕНИЕ, и оно защищается тестом.

    Через этот же сервер качается .exe на 50 МБ. Любой разумный `write` оборвал бы
    закачку на медленном канале — то есть обновление десктопа перестало бы доезжать до
    людей, причём молча и только у тех, у кого связь плохая. Защита от медленного
    ЧТЕНИЯ ответа — это лимит соединений, а не таймаут записи."""
    body = _uncommented(conf)
    assert not re.search(r"^\s*write\s+\d+[sm]\s*$", body, re.M), (
        "появился таймаут write — он оборвёт закачку 50-мегабайтного .exe на медленном "
        "канале, и обновление десктопа тихо перестанет доезжать")


def _check_body_is_capped(conf: str) -> None:
    """Лимита не было вовсе: любой желающий мог слать в /auth/login тело на гигабайт, и
    мы честно принимали его в память машины с 960 МБ. Самый дешёвый способ положить
    сервер — трафик атакующего оплачивает провайдер, память тратим мы."""
    assert re.findall(r"max_size\s+(\d+)MB", _uncommented(conf)), (
        "request_body без max_size — тело запроса снова не ограничено ничем")


def _check_import_cap_is_the_widest(conf: str) -> None:
    """Лимитов ДВА, и соотношение между ними значимо: у импорта выгрузки данных (zip со
    справочниками) свой широкий, у всего остального — узкий. Сравняются — либо админ не
    зальёт архив, либо узкого лимита не станет ни у чего."""
    body = _uncommented(conf)
    assert "/web/admin/data/import" in body, (
        "исчез отдельный матчер импорта — админ упрётся в общий лимит и не зальёт архив")
    sizes = sorted(int(s) for s in re.findall(r"max_size\s+(\d+)MB", body))
    assert len(sizes) >= 2, "остался один лимит на всё — либо импорт сломан, либо защиты нет"
    assert sizes[-1] > sizes[0], "лимит импорта не шире общего — один из них бессмыслен"
    assert sizes[0] <= 16, (
        "общий лимит тела %dMB — слишком щедро для формы входа и настроек" % sizes[0])


# ── Журнал доступа ─────────────────────────────────────────────────────────────────
def _check_access_log_rolls(conf: str) -> None:
    """Журнал нужен fail2ban и нам. Но БЕЗ РОТАЦИИ он однажды доест остаток диска,
    забитого на три четверти, — и сервер ляжет не от атаки, а от собственного лога."""
    body = _uncommented(conf)
    assert re.search(r"output\s+file\s+\S*access\.log", body), "журнал доступа не пишется"
    assert "roll_size" in body, "у журнала нет roll_size — он будет расти до конца диска"
    assert "roll_keep" in body, "у журнала нет roll_keep — старые куски не удаляются"


# ── Заголовки, которые снимаются с ответа ──────────────────────────────────────────
def _check_fingerprint_headers_are_stripped(conf: str) -> None:
    """`Server` и `Via` называют атакующему наш прокси — бесплатная подсказка для
    подбора эксплойта. ⚠️ `Via` снимается в блоке `header`, а НЕ в `reverse_proxy`:
    Caddy добавляет его на транспортном слое, и `header_down` (правит только ответ
    апстрима) до него не достаёт."""
    body = _uncommented(conf)
    for h in ("-Server", "-Via"):
        assert re.search(r"^\s*%s\s*$" % re.escape(h), body, re.M), (
            "%s пропал — ответ снова называет наш прокси" % h)


# ── Раздача статики ────────────────────────────────────────────────────────────────
def _check_static_is_precompressed(conf: str) -> None:
    """Файлы пожаты ОДИН РАЗ при выкладке (.zst/.gz рядом с оригиналом). На одном ядре
    это принципиально: без этого каждый промах кэша пережимал бы бандл в 1.3 МБ заново,
    и сжатие из выигрыша превратилось бы в постоянную нагрузку."""
    assert re.search(r"precompressed\s+.*zstd", _uncommented(conf)), (
        "статика больше не отдаётся предсжатой — единственное ядро начнёт жать её на лету")


def _check_easter_assets_revalidate(conf: str) -> None:
    """🔥 КУПЛЕНО ОШИБКОЙ (23.08.2026). Арт пасхалок положили в общую «недельную»
    корзину вместе со шрифтами — и следующая правка рисунка не доехала до человека
    вовсе: на сервере лежал новый файл, а браузер неделю показывал старый. Со стороны
    это выглядит как «вы не починили», и проверить нечем — сервер отдаёт правильное.

    Разница со шрифтами не в размере, а в ЖИЗНЕННОМ ЦИКЛЕ: шрифт кладут один раз, арт
    правится по живым отзывам. Хеша в имени у него нет — значит единственный честный
    способ это проверка на свежесть."""
    body = _uncommented(conf)
    m = re.search(r"@easter\s+path\s+/easter/\*", body)
    assert m, "исчез отдельный матчер /easter/* — арт пасхалок вернулся в недельный кэш"
    tail = body[m.end():m.end() + 300]
    assert "must-revalidate" in tail and "max-age=0" in tail, (
        "у /easter/* больше не проверяется свежесть — правка рисунка не доедет до людей")


def _check_immutable_is_only_for_hashed(conf: str) -> None:
    """`immutable` означает «браузер не переспросит НИКОГДА». Это правда только для
    /assets/*, где имя содержит хеш содержимого (Vite). Выдать его шрифтам или спрайтам,
    у которых имя постоянное, значит сделать их незаменяемыми на год."""
    body = _uncommented(conf)
    m = re.search(r"@immutable\s+path\s+([^\n]+)", body)
    assert m, "исчез матчер @immutable"
    paths = m.group(1).split()
    assert paths == ["/assets/*"], (
        "immutable выдан не только хешированным ассетам: %s — эти файлы станет "
        "невозможно заменить в течение года" % paths)


def _check_compression_matches_only_text(conf: str) -> None:
    """Без `match` Caddy тратил бы единственное ядро на webp-спрайты и woff2 — они уже
    сжаты, и повторное сжатие даёт минус по времени и плюс по нагрузке."""
    body = _uncommented(conf)
    m = re.search(r"encode\s+[^{]*\{(.*?)\n\t\}", body, re.S)
    assert m, "не разобрался блок encode"
    block = m.group(1)
    assert "match" in block, (
        "у encode пропал match — ядро начнёт пережимать уже сжатые картинки и шрифты")
    assert "minimum_length" in block, (
        "пропал minimum_length — мелкие ответы API будут жаться себе в убыток")


# ── Анти-брутфорс ──────────────────────────────────────────────────────────────────
def _check_real_client_ip_reaches_the_app(conf: str) -> None:
    """🔒 Сервер (throttle.client_ip) считает попытки входа ПО IP. Он доверяет
    X-Real-IP, а ставит его сюда Caddy из ПРОВЕРЕННОГО TCP-пира — клиент подделать не
    может. Уберите строку, и приложение начнёт верить первому элементу X-Forwarded-For,
    который шлёт сам клиент: защита от перебора пароля обходится сменой одного
    заголовка, то есть перестаёт существовать."""
    assert re.search(r"header_up\s+X-Real-IP\s+\{remote_host\}", _uncommented(conf)), (
        "X-Real-IP больше не ставится из TCP-пира — анти-брутфорс обходится подделкой "
        "заголовка")


def _check_h2_is_enabled(conf: str) -> None:
    """HTTP/2 мультиплексирует запросы в одном соединении. У SPA их на первой загрузке
    десятки, и на одном ядре это разница между «сайт открылся» и «сайт открывается»."""
    m = re.search(r"protocols\s+([^\n]+)", _uncommented(conf))
    assert m, "блок protocols пропал"
    assert "h2" in m.group(1).split(), "HTTP/2 выключен: protocols %s" % m.group(1)


# ── Прямые тесты: каждая проверка на боевом файле ──────────────────────────────────
_CHECKS = [
    ("read_header против slowloris", _check_read_header_timeout),
    ("write-таймаут не задан намеренно", _check_write_timeout_is_absent),
    ("тело запроса ограничено", _check_body_is_capped),
    ("у импорта свой широкий лимит", _check_import_cap_is_the_widest),
    ("журнал доступа ротируется", _check_access_log_rolls),
    ("Server и Via снимаются", _check_fingerprint_headers_are_stripped),
    ("статика предсжата", _check_static_is_precompressed),
    ("арт пасхалок проверяется на свежесть", _check_easter_assets_revalidate),
    ("immutable только у хешированных", _check_immutable_is_only_for_hashed),
    ("сжимается только сжимаемое", _check_compression_matches_only_text),
    ("реальный IP доходит до анти-брутфорса", _check_real_client_ip_reaches_the_app),
    ("HTTP/2 включён", _check_h2_is_enabled),
]


@pytest.mark.parametrize("name, check", _CHECKS, ids=[n for n, _ in _CHECKS])
def test_production_config_holds(conf, name, check):
    """Боевой конфиг удовлетворяет каждому утверждению из списка."""
    check(conf)


# ── ОБРАТНЫЙ ХОД ───────────────────────────────────────────────────────────────────
# Инвариант проекта: сторож, не проверенный откатом, скорее всего не работает, и это не
# фигура речи — `pollingRespectsVisibility` пришлось чинить ЧЕТЫРЕ раза, и каждый раз
# ошибку ловил обратный ход, а не чтение. Здесь ломается ровно та строка, ради которой
# проверка написана, и от неё требуется покраснеть.
_BREAKAGES = [
    (_check_read_header_timeout, lambda c: c.replace("read_header 15s", ""),
     "убрали read_header"),
    (_check_read_header_timeout, lambda c: c.replace("read_header 15s", "read_header 10m"),
     "растянули read_header до 10 минут - slowloris снова проходит"),
    (_check_write_timeout_is_absent, lambda c: c.replace("idle 5m", "write 30s"),
     "добавили write-таймаут - оборвёт закачку .exe"),
    (_check_body_is_capped, lambda c: re.sub(r"max_size\s+\d+MB", "", c),
     "сняли лимит тела запроса"),
    (_check_import_cap_is_the_widest, lambda c: c.replace("max_size 200MB", "max_size 4MB"),
     "сравняли лимит импорта с общим"),
    (_check_import_cap_is_the_widest, lambda c: c.replace("max_size 4MB", "max_size 512MB"),
     "общий лимит стал щедрее импорта"),
    (_check_access_log_rolls, lambda c: c.replace("roll_size 20MiB", ""),
     "убрали ротацию журнала - он доест диск"),
    (_check_fingerprint_headers_are_stripped, lambda c: c.replace("\n\t\t-Via", ""),
     "перестали снимать Via"),
    (_check_fingerprint_headers_are_stripped, lambda c: c.replace("\n\t\t-Server", ""),
     "перестали снимать Server"),
    (_check_static_is_precompressed, lambda c: c.replace("precompressed zstd gzip", ""),
     "статика больше не предсжата"),
    (_check_easter_assets_revalidate,
     lambda c: c.replace("max-age=0, must-revalidate", "max-age=604800"),
     "вернули пасхалкам недельный кэш - ровно дефект 23.08.2026"),
    (_check_immutable_is_only_for_hashed,
     lambda c: c.replace("@immutable path /assets/*", "@immutable path /assets/* /fonts/*"),
     "выдали immutable шрифтам - их не заменить год"),
    (_check_compression_matches_only_text,
     lambda c: re.sub(r"\t\tmatch \{.*?\n\t\t\}", "", c, flags=re.S),
     "сняли match у encode - ядро жмёт уже сжатое"),
    (_check_compression_matches_only_text, lambda c: c.replace("minimum_length 1024", ""),
     "сняли minimum_length"),
    (_check_real_client_ip_reaches_the_app,
     lambda c: c.replace("header_up X-Real-IP {remote_host}", ""),
     "убрали X-Real-IP - анти-брутфорс обходится подделкой заголовка"),
    (_check_h2_is_enabled, lambda c: c.replace("protocols h1 h2", "protocols h1"),
     "выключили HTTP/2"),
]


@pytest.mark.parametrize("check, break_it, why", _BREAKAGES,
                         ids=[w for _, _, w in _BREAKAGES])
def test_the_guard_actually_fires(conf, check, break_it, why):
    """Ломаем конфиг в памяти и требуем, чтобы проверка это заметила.

    Зелёный тест рядом со сломанным конфигом хуже отсутствия теста: он неотличим от
    исправного и создаёт ощущение защиты."""
    broken = break_it(conf)
    assert broken != conf, (
        "поломка «%s» не изменила конфиг — значит проверка зелёная не потому, что "
        "сторож работает, а потому что ломать было нечего. Правьте поломку." % why)
    with pytest.raises(AssertionError):
        check(broken)


# ═══════════════════════════════════════════════════════════════════════════════════
# ЧАСТЬ 3 — КОНФИГОВ В РЕПОЗИТОРИИ БОЛЬШЕ ОДНОГО, И ЛИШНИЕ ОПАСНЫ (03.09.2026).
#
# Части 1 и 2 стерегли `server/Caddyfile` и делали это хорошо. Но в репозитории лежал
# ВТОРОЙ конфиг — `web/deploy/Caddyfile` от 11.07.2026 — и он не был виден ни одному
# тесту. Внутри: чужой домен, НИ ОДНОГО заголовка безопасности, нет лимита тела, нет
# таймаутов и — главное — пересылка БЕЛЫМ СПИСКОМ путей, ровно тот дефект, от которого
# боевой конфиг предостерегает в комментарии. В белом списке нет `/app/*`,
# `/downloads/*`, `/desktop/updates`, `/public/schedule*`, `/schedule/*`: развернувший
# по нему получит живой вход, зелёный сайт и 404 там, где у людей обновления телефонов,
# обновление десктопа и расписание.
#
# ⚠️ И это не гипотетический читатель. Переезд на железо ВСГУТУ уже назначен (§5.2.4.1
# политики вуза — обработка ПДн не поручается другому лицу), разворачивать будет их
# администратор, и искать он будет файл с именем Caddyfile.
#
# Решение не «удалить и забыть»: удалённый образец вернётся следующим черновиком.
# Правило вводится общее — БОЕВОЙ КОНФИГ РОВНО ОДИН, всякий другой обязан кричать о
# себе в первых строках. Это тот же приём, что в проекте уже принят для исключений:
# «исключение без записанной причины — не исключение, а забытый случай».
# ═══════════════════════════════════════════════════════════════════════════════════

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Единственный конфиг, по которому разворачивают бой. Путь от корня репозитория.
_PRODUCTION_CONFIG = os.path.join("server", "Caddyfile")

# Маркер, который обязан стоять в первых строках любого НЕбоевого конфига.
_SAMPLE_MARKER = "НЕ БОЕВОЙ КОНФИГ"

# Каталоги, куда не ходим: чужой код и артефакты сборки.
_SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "nuitka_out",
              "graphify-out", "__pycache__", ".mypy_cache", "android"}


def _find_server_configs() -> list:
    """Все файлы репозитория, похожие на конфиг веб-сервера, — путями от корня."""
    found = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fname in files:
            low = fname.lower()
            if low.startswith("caddyfile") or low == "nginx.conf":
                found.append(os.path.relpath(os.path.join(root, fname), REPO_ROOT))
    return sorted(found)


def test_the_production_config_is_where_the_tests_look():
    """Боевой конфиг на месте. Переедет — вся первая часть тестов станет проверять
    пустоту, и мы узнаем об этом от Caddy на бою, а не здесь."""
    configs = _find_server_configs()
    assert _PRODUCTION_CONFIG.replace("\\", "/") in [c.replace("\\", "/") for c in configs], (
        "server/Caddyfile не найден обходом репозитория: %s" % configs)


def test_every_other_config_is_marked_as_a_sample():
    """🔥 Всякий конфиг, кроме боевого, обязан нести маркер в первых строках.

    Обратный ход: снять шапку у `web/deploy/Caddyfile` — тест краснеет (проверено
    откатом 03.09.2026)."""
    unmarked = []
    for rel in _find_server_configs():
        if rel.replace("\\", "/") == _PRODUCTION_CONFIG.replace("\\", "/"):
            continue
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            head = "".join(fh.readlines()[:25])
        if _SAMPLE_MARKER not in head:
            unmarked.append(rel)
    assert not unmarked, (
        "конфиг(и) без пометки образца: %s.\n"
        "Боевой у продукта РОВНО ОДИН — server/Caddyfile. Всякий другой файл с таким "
        "именем однажды возьмут для развёртывания (искать будут по имени), и он обязан "
        "в первых строках сказать, что он не боевой и чего в нём нет. Либо пометьте, "
        "либо удалите." % unmarked)


def test_a_sample_config_warns_about_its_path_whitelist():
    """Образец с белым списком путей обязан назвать ИМЕННО эту опасность, а не
    отделаться общим «не для боя».

    Причина в цене ошибки: остальные пропуски образца (нет CSP, нет лимита тела) видны
    при первом же взгляде специалиста, а забытый путь в белом списке не виден вообще —
    сайт открывается, вход работает, и только обновления телефонов молча отдают 404."""
    for rel in _find_server_configs():
        if rel.replace("\\", "/") == _PRODUCTION_CONFIG.replace("\\", "/"):
            continue
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
            text = fh.read()
        body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        # Белый список = матчер по path с перечислением префиксов.
        has_whitelist = bool(re.search(r"@\w+\s+path\s+/\w+/\*.*/\w+", body)) or bool(
            re.search(r"location\s+~?\s*\^?\(?/\w+\|", body))
        if not has_whitelist:
            continue
        head = "\n".join(text.splitlines()[:25])
        assert "БЕЛЫМ СПИСКОМ" in head or "белым списком" in head, (
            "%s пересылает по белому списку путей, но шапка об этом не предупреждает. "
            "Забытый путь в таком списке — это не «медленно», это 404 на обновлениях "
            "телефонов, обновлении десктопа и расписании без входа." % rel)


def test_the_dead_samples_do_not_claim_our_domain():
    """Образцы называют чужой домен (`gradebookai.ru`), боевой — `esstu-gradebook.ru`.

    Проверка не косметическая: совпади они, и различить боевой конфиг с образцом стало
    бы невозможно взглядом — а именно взглядом его и будут выбирать."""
    prod = open(os.path.join(REPO_ROOT, _PRODUCTION_CONFIG), encoding="utf-8").read()
    m = re.search(r"^([\w.-]+)\s*\{", _uncommented(prod), re.M)
    assert m, "в боевом конфиге не нашёлся блок домена"
    prod_domain = m.group(1)
    for rel in _find_server_configs():
        if rel.replace("\\", "/") == _PRODUCTION_CONFIG.replace("\\", "/"):
            continue
        text = open(os.path.join(REPO_ROOT, rel), encoding="utf-8").read()
        body = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        assert prod_domain not in body, (
            "%s содержит БОЕВОЙ домен %s — образец стал неотличим от боевого конфига, "
            "и однажды развернут будет он" % (rel, prod_domain))
