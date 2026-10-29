"""Оформление вечерней сводки: HTML-письмо с анимациями и пояснениями (04.10.2026).

Цифры собирает `nightly_report.collect`; здесь — только то, как их показать. Просьба
Ярослава: «ВАУ, очень красивое и познавательное, и на телефонах и на компах».

━━ КАК ЗДЕСЬ ДОСТИГАЕТСЯ АНИМАЦИЯ ━━
Gmail вырезает `@keyframes`, SVG и скрипты, но проигрывает анимированный GIF. Поэтому:
  • Вектор машет (всё хорошо) или думает (есть что посмотреть) — готовые GIF из
    `report_assets/` (собирает `tools/build_report_assets.py` из роликов Арины);
  • графики растут при открытии — GIF рисует `report_charts` (Pillow);
  • радар приманок и пульсирующий индикатор статуса — тоже GIF;
  • CSS-анимации (появление блоков, полоски стран, свечение) — надстройка для Apple
    Mail, iOS и Thunderbird. Они стоят ОТДЕЛЬНЫМ блоком `<style>`: если клиент
    выбросит его целиком, раскладка и адаптивность из соседнего блока останутся.
  ⚠️ Ни один элемент не прячется в исходном состоянии (`opacity:0` только внутри
  `@keyframes`): клиент, вырезавший анимацию, обязан показать всё.

━━ КАК ЗДЕСЬ ДОСТИГАЕТСЯ «И НА ТЕЛЕФОНЕ, И НА КОМПЬЮТЕРЕ» ━━
Числа — сетка 2×2 таблицей с ширинами в процентах, состояние сервера — список строк.
Прежние блоки `inline-block` фиксированной ширины Gmail на телефоне ставил по одному в
ряд, и письмо вытягивалось в длинную ленту (жалоба 27.10.2026). Ячейка в 50 % держит два
числа в ряд в любом клиенте, media-запросы для этого не нужны.

━━ ГРАНИЦА ПДн ━━
🔒 Ни IP, ни логинов, ни ФИО (письмо хранится у Google) — см. шапку `nightly_report`.
Всё, что прислал атакующий (путь, инструмент), экранируется: иначе путь вида
`/<script>` стал бы разметкой в нашем же отчёте.
"""
from __future__ import annotations

import html
import os
from datetime import datetime

import college_clock  # noqa: E402

#Пояс колледжа — одна дверь `college_clock`; здесь стояла своя константа +480 мин.
_TZ = college_clock.TZ
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_assets")

#Цвет «окошка» Вектора — ОБЯЗАН совпадать с HERO_BG в tools/build_report_assets.py:
#фон вшит в кадры GIF, и при расхождении вокруг тигра проступит прямоугольник.
HERO_PANEL = "#E0F5F7"

ACCENT, DEEP, BRIGHT = "#147C8B", "#0B4F59", "#22A6B3"
OK, WARN, BAD = "#1F9D6B", "#D68910", "#C0392B"
TEXT, MUTED, LINE, SOFT, PAGE = "#17262A", "#64777B", "#E1E9EB", "#F5F9FA", "#EAF1F3"
_e = html.escape

_COUNTRY_RU = {
    "RU": "Россия", "US": "США", "CN": "Китай", "DE": "Германия", "NL": "Нидерланды",
    "GB": "Великобритания", "FR": "Франция", "SG": "Сингапур", "HK": "Гонконг",
    "JP": "Япония", "KR": "Южная Корея", "IN": "Индия", "BR": "Бразилия",
    "CA": "Канада", "UA": "Украина", "BY": "Беларусь", "KZ": "Казахстан",
    "TR": "Турция", "VN": "Вьетнам", "ID": "Индонезия", "IR": "Иран",
    "PL": "Польша", "RO": "Румыния", "BG": "Болгария", "SE": "Швеция",
    "FI": "Финляндия", "LT": "Литва", "LV": "Латвия", "EE": "Эстония",
    "CZ": "Чехия", "IT": "Италия", "ES": "Испания", "AU": "Австралия",
    "MN": "Монголия", "TW": "Тайвань", "TH": "Таиланд", "SC": "Сейшелы",
    "BE": "Бельгия", "CH": "Швейцария", "AT": "Австрия", "IE": "Ирландия",
    "ZA": "ЮАР", "MX": "Мексика", "AR": "Аргентина", "IL": "Израиль",
    "PK": "Пакистан", "BD": "Бангладеш", "PH": "Филиппины", "MY": "Малайзия",
}

#━━ СПРАВОЧНИК: ЧТО ЭТО ЗА ИНСТРУМЕНТ ━━
#Познавательная часть письма: голое «Go http-client» ничего не говорит, а «так выглядит
#большинство облачных сканеров» объясняет, почему это шум, а не целевая атака.
TOOL_HINTS = {
    "Nuclei": "сканер уязвимостей по шаблонам: за минуту проверяет тысячи известных дыр",
    "sqlmap": "ищет SQL-инъекции, чтобы вытащить содержимое базы",
    "Nikto": "старый сканер веб-серверов на типовые ошибки настройки",
    "WPScan": "сканер WordPress — у нас его нет, ищут чужую CMS",
    "Nmap": "сканер портов и служб: составляет карту открытых дверей",
    "masscan": "сверхбыстрый сканер портов всего интернета",
    "ZGrab": "собирает «визитки» серверов для поисковиков вроде Censys",
    "Gobuster": "перебирает пути по словарю в поисках забытых файлов",
    "ffuf": "перебирает пути по словарю в поисках забытых файлов",
    "feroxbuster": "перебирает пути по словарю в поисках забытых файлов",
    "DirBuster": "перебирает пути по словарю в поисках забытых файлов",
    "GitFinder": "ищет забытую папку .git, чтобы скачать исходный код сайта",
    "LeakIX": "поисковик утечек: открытые .env, .git, базы без пароля",
    "Censys": "поисковик по интернету: держит карту открытых серверов",
    "Palo Alto Expanse": "коммерческий обходчик «поверхности атаки» компаний",
    "InternetMeasurement": "исследовательский обходчик интернета",
    "curl": "консольная утилита: кто-то проверял адрес руками или скриптом",
    "Wget": "консольная утилита для скачивания — пробовали забрать файл",
    "python-requests": "самописный скрипт на Python",
    "python-httpx": "самописный скрипт на Python",
    "Python urllib": "самописный скрипт на Python",
    "Go http-client": "программа на Go — так выглядит большинство облачных сканеров",
    "без User-Agent": "клиент даже не представился — почти всегда автомат",
}
#Короткая подпись типа — рядом с названием; пояснение — строкой ниже. Разные словари:
#одна строка в обоих местах читалась бы как повтор.
KIND_LABELS = {
    "scanner": "сканер уязвимостей", "script": "скрипт или утилита",
    "bot": "робот-обходчик", "empty": "без подписи", "browser": "строка браузера",
    "other": "неизвестный клиент", "ours": "наше приложение",
}
KIND_HINTS = {
    "scanner": "автоматический поиск известных уязвимостей",
    "script": "кто-то запустил программу, а не открыл сайт в браузере",
    "bot": "обходчик поисковика или сервиса — на приманку попал случайно",
    "empty": "клиент даже не представился — почти всегда автомат",
    "browser": "строку браузера подделать проще всего — признаки автоматики в разделе",
    "other": "клиент с необычной подписью",
    "ours": "наше приложение — на приманку оно ходить не должно",
}
KIND_COLOR = {"scanner": BAD, "script": WARN, "bot": ACCENT, "empty": BAD,
              "browser": MUTED, "other": MUTED, "ours": OK}

#Что искали: от узкого к широкому, первое совпадение выигрывает.
PATH_HINTS = (
    ("/auth/login", "вход учёткой-приманкой: её логин есть только в дампе базы"),
    (".env", "файл с паролями и ключами приложения"),
    (".git", "служебная папка git: по ней восстанавливают исходный код"),
    ("xmlrpc", "WordPress XML-RPC: перебор паролей пачками"),
    ("wp-", "WordPress — у нас его нет, ищут чужую CMS со слабым паролем"),
    (".aws", "ключи облака Amazon"),
    (".docker", "настройки Docker с токенами реестра"),
    (".claude", "конфиг ИИ-ассистента: там ищут API-ключи"),
    (".anthropic", "конфиг ИИ-ассистента: там ищут API-ключи"),
    (".config", "конфиги облачных утилит с ключами доступа"),
    (".ssh", "ключи SSH — доступ к серверу"),
    ("id_rsa", "ключи SSH — доступ к серверу"),
    ("phpmyadmin", "панель управления базой MySQL"),
    (".sql", "дамп базы данных"),
    ("config.json", "файл настроек — иногда с паролями"),
    ("credentials", "файл с учётными данными"),
    ("server-status", "страница состояния Apache"),
    (".php", "PHP-скрипт — у нас PHP нет вовсе, это перебор чужих CMS"),
)
CLOUD_MARKS = ("GOOGLE", "AMAZON", "AWS", "MICROSOFT", "AZURE", "DIGITALOCEAN", "OVH",
               "HETZNER", "LINODE", "AKAMAI", "VULTR", "CHOOPA", "ALIBABA", "TENCENT",
               "ORACLE", "CONTABO", "M247", "LEASEWEB", "SCALEWAY", "CLOUDFLARE")

#━━ ФАКТ ДНЯ — Вектор объясняет, как устроена защита ━━
FACTS = (
    ("Приманка — детектор, а не щит",
     "Она не мешает войти — она делает попытку заметной. К этим путям не ходит никто "
     "законный, поэтому любое обращение уже сигнал, без порогов и ложных тревог."),
    ("Почему сканеры живут в облаках",
     "Арендовать машину в Google Cloud или DigitalOcean на час дешевле, чем прятаться. "
     "Поэтому в списке провайдеров так часто облака: это массовый обход, а не охота на нас."),
    ("Пароль к SSH подобрать нельзя",
     "Вход по паролю на сервер выключен — пускают только ключи. Тысячи попыток в день "
     "бьются в закрытую дверь, а fail2ban ещё и выставляет самых упорных."),
    ("Копия, из которой не восстанавливались, — надежда",
     "Каждую ночь база снимается VACUUM INTO на зашифрованном соединении и проверяется "
     "integrity_check. Копия без проверки восстановлением ничего не гарантирует."),
    ("Журнал, который замечает правку",
     "Каждая запись журнала безопасности хранит хеш предыдущей. Удалить или поменять "
     "строку незаметно нельзя — цепочка перестанет сходиться."),
    ("Почему в письме нет адресов",
     "IP-адрес — персональные данные, если его можно связать с человеком. Письмо хранится "
     "у Google, а политика ВСГУТУ запрещает трансграничную передачу. Адреса — в разделе."),
    ("База зашифрована целиком",
     "SQLCipher шифрует файл базы AES-256. Украденный файл без ключа — это шум: ни "
     "оценок, ни ФИО из него не прочитать."),
    ("Мина для взломщика",
     "Ответ приманки отдаёт «случайно забытый» хеш служебной учётки. Он из случайных "
     "байт — прообраза нет, и перебор на видеокарте не закончится никогда."),
    ("Браузер без языка — не человек",
     "Настоящий браузер всегда сообщает язык и шлёт заголовки Sec-Fetch. Сканер, "
     "подделавший строку Chrome, обычно про них забывает — так его и отличают."),
    ("Бан на сутки, а не навсегда",
     "Вечный бан оборачивается разблокировкой руками. За сутки автоматический сканер "
     "уходит и не возвращается, а живой человек не останется отрезанным навсегда."),
    ("HTTPS продлевается сам",
     "Сертификат Let's Encrypt живёт 90 дней, Caddy продлевает его за 30 дней до конца. "
     "Если в сводке осталось меньше двух недель — продление где-то встало."),
    ("Учётка-приманка",
     "В пути входа спрятан логин, которого нет среди людей. Узнать его можно только из "
     "дампа базы, поэтому попытка войти под ним — доказательство утечки."),
)

ROLE_RU = {"student": ("🎓", "студенты"), "teacher": ("👩‍🏫", "преподаватели"),
           "parent": ("👪", "родители"), "admin": ("🛡", "администрация"),
           "moderator": ("🧭", "модераторы")}


# ── маленькие помощники ─────────────────────────────────────────────────────────────
def _flag(cc: str) -> str:
    cc = (cc or "").upper()
    if len(cc) != 2 or not cc.isalpha():
        return "🏳"
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)


def country_name(cc: str) -> str:
    return _COUNTRY_RU.get((cc or "").upper(), cc or "неизвестно")


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def path_hint(path: str) -> str:
    low = (path or "").lower()
    for needle, hint in PATH_HINTS:
        if needle in low:
            return hint
    return "служебный путь, к которому не обращается никто законный"


def tool_hint(tool: str, kind: str) -> str:
    return TOOL_HINTS.get(tool) or KIND_HINTS.get(kind, "")


def is_cloud(name: str) -> bool:
    up = (name or "").upper()
    return any(m in up for m in CLOUD_MARKS)


def fact_of_the_day(ts: float) -> tuple:
    day = datetime.fromtimestamp(ts, _TZ).timetuple().tm_yday
    return FACTS[day % len(FACTS)]


def _mb(n) -> str:
    if not n:
        return "—"
    return "%.1f ГБ" % (n / 2 ** 30) if n >= 2 ** 30 else "%.0f МБ" % (n / 2 ** 20)


def _dur(sec) -> str:
    sec = int(sec or 0)
    d, h = sec // 86400, (sec % 86400) // 3600
    return ("%d дн %d ч" % (d, h)) if d else ("%d ч %d мин" % (h, (sec % 3600) // 60))


def _delta(cur, prev, good_up: bool = True) -> str:
    """Стрелка к вчерашним суткам. Цвет — по смыслу: рост входов хорош, рост атак плох."""
    if prev is None:
        return ""
    cur, prev = int(cur or 0), int(prev or 0)
    if cur == prev:
        return ("<span style='display:inline-block;font-size:11px;color:%s;background:%s;"
                "border-radius:999px;padding:2px 8px'>= как вчера</span>" % (MUTED, SOFT))
    up = cur > prev
    good = up == good_up
    col, bg = (OK, "#E3F5EC") if good else (BAD, "#FBE7E4")
    return ("<span style='display:inline-block;font-size:11px;font-weight:700;color:%s;"
            "background:%s;border-radius:999px;padding:2px 8px'>%s %d к вчера</span>"
            % (col, bg, "▲" if up else "▼", abs(cur - prev)))


def _asset(name: str) -> bytes | None:
    try:
        with open(os.path.join(ASSETS, name), "rb") as fh:
            return fh.read()
    except OSError:
        return None


# ── крупные блоки ───────────────────────────────────────────────────────────────────
def _card(title: str, body: str, *, icon: str = "", sub: str = "", delay: int = 1) -> str:
    head = ("<table role='presentation' cellspacing='0' cellpadding='0' style='margin-bottom:8px'>"
            "<tr>%s<td style='vertical-align:middle'><div style='font-size:16px;font-weight:800;"
            "color:%s;letter-spacing:-.01em'>%s</div>%s</td></tr></table>"
            % (("<td style='vertical-align:middle;padding-right:10px;font-size:20px;"
                "line-height:1'>%s</td>" % icon) if icon else "", TEXT, _e(title),
               ("<div style='font-size:12px;color:%s;margin-top:1px'>%s</div>"
                % (MUTED, _e(sub))) if sub else ""))
    return ("<div class='gb-up gb-d%d' style='background:#ffffff;border:1px solid %s;"
            "border-radius:18px;padding:14px 14px 12px;margin:0 0 12px;"
            "box-shadow:0 4px 16px rgba(11,79,89,.06)'>%s%s</div>"
            % (delay, LINE, head, body))


def _kpi(emoji: str, label: str, value, note: str = "", delta: str = "",
         color: str = TEXT) -> str:
    """Одна клетка сетки чисел; сетку собирает `_kpi_grid`."""
    return ("<div style='background:%s;border:1px solid %s;border-radius:14px;"
            "padding:9px 11px 10px'><div style='font-size:12px;color:%s'>%s&nbsp;%s</div>"
            "<div style='font-size:23px;font-weight:800;color:%s;line-height:1.2;"
            "margin:3px 0 1px;letter-spacing:-.02em'>%s</div>"
            "<div style='font-size:11.5px;line-height:1.35;color:%s'>%s</div>%s</div>"
            % (SOFT, LINE, MUTED, emoji, _e(label), color, _e(str(value)), MUTED,
               _e(note) if note else "&nbsp;",
               ("<div style='margin-top:5px'>%s</div>" % delta) if delta else ""))


def _kpi_grid(cells: list) -> str:
    """Числа сеткой по два в ряд — таблицей с ширинами в процентах (см. шапку модуля)."""
    rows = []
    for i in range(0, len(cells), 2):
        pair = (cells[i:i + 2] + [""])[:2]
        rows.append("<tr>" + "".join(
            "<td width='50%%' style='width:50%%;padding:3px;vertical-align:top'>%s</td>" % c
            for c in pair) + "</tr>")
    return ("<table role='presentation' width='100%' cellspacing='0' cellpadding='0' "
            "style='table-layout:fixed'>" + "".join(rows) + "</table>")


def _status_row(label: str, value: str, state: str = "ok", first: bool = False) -> str:
    """Строка «● название ……… значение» — состояние сервера и защиты списком."""
    col = {"ok": OK, "warn": WARN, "bad": BAD}.get(state, MUTED)
    line = "" if first else "border-top:1px solid %s;" % LINE
    return ("<tr><td style='%spadding:8px 8px 8px 0;width:10px;vertical-align:top'>"
            "<div style='width:9px;height:9px;border-radius:50%%;background:%s;"
            "margin-top:5px'></div></td><td style='%spadding:8px 8px 8px 0;font-size:13.5px;"
            "color:%s;vertical-align:top'>%s</td><td style='%spadding:8px 0;font-size:13.5px;"
            "font-weight:700;color:%s;text-align:right;vertical-align:top'>%s</td></tr>"
            % (line, col, line, TEXT, _e(label), line, TEXT, _e(value)))


def _status_note(text: str) -> str:
    """Подстрока под строкой состояния: что именно нашлось или поставилось."""
    return ("<tr><td></td><td colspan='2' style='padding:0 0 7px;font-size:12px;"
            "line-height:1.4;color:%s'>%s</td></tr>" % (MUTED, _e(text)))


def _status_table(rows: list) -> str:
    return ("<table role='presentation' width='100%' cellspacing='0' cellpadding='0'>"
            + "".join(rows) + "</table>")


def _chart(cid: str, alt: str, fallback: str, has_image: bool, height: int = 190) -> str:
    if has_image:
        return ("<img src='cid:%s' width='600' alt='%s' style='display:block;width:100%%;"
                "max-width:600px;height:auto;border:0;border-radius:12px'>" % (cid, _e(alt)))
    return fallback


def _html_bars(week: list, color: str) -> str:
    """Запасные столбики таблицей — если Pillow на машине нет (GIF не нарисован)."""
    peak = max([w["n"] for w in week] or [0]) or 1
    cols = []
    for i, w in enumerate(week):
        h = max(int(90 * w["n"] / peak), 3)
        c = color if i == len(week) - 1 else color + "66"
        cols.append("<td style='vertical-align:bottom;text-align:center;padding:0 4px'>"
                    "<div style='font-size:12px;font-weight:700;color:%s'>%d</div>"
                    "<div class='gb-rise' style='height:%dpx;background:%s;"
                    "border-radius:8px 8px 3px 3px;margin-top:3px'></div>"
                    "<div style='font-size:11px;color:%s;margin-top:5px'>%s</div></td>"
                    % (TEXT, w["n"], h, c, MUTED, _e(w["date"][8:10] + "." + w["date"][5:7])))
    return ("<table role='presentation' width='100%' cellspacing='0' cellpadding='0' "
            "style='height:140px'><tr>" + "".join(cols) + "</tr></table>")


def _meter(label_html: str, n: int, peak: int, color: str, tail: str = "") -> str:
    pct = max(4, int(100 * n / (peak or 1)))
    return ("<div style='margin:9px 0'><table role='presentation' width='100%%' "
            "cellspacing='0' cellpadding='0'><tr><td style='font-size:13.5px;color:%s'>%s</td>"
            "<td style='font-size:13.5px;font-weight:800;color:%s;text-align:right;"
            "white-space:nowrap'>%d</td></tr></table><div style='background:%s;"
            "border-radius:999px;height:8px;margin-top:5px;overflow:hidden'>"
            "<div class='gb-bar' style='width:%d%%;height:8px;border-radius:999px;"
            "background:%s;background-image:linear-gradient(90deg,%s,%s)'></div></div>%s</div>"
            % (TEXT, label_html, TEXT, n, "#EEF3F4", pct, color, color, color + "AA",
               ("<div style='font-size:11.5px;color:%s;margin-top:4px'>%s</div>" % (MUTED, tail))
               if tail else ""))


def _sub(title: str) -> str:
    return ("<div style='font-size:11.5px;font-weight:700;color:%s;text-transform:uppercase;"
            "letter-spacing:.08em;margin:14px 0 4px'>%s</div>" % (MUTED, _e(title)))


def _vector_line(d: dict) -> str:
    """Реплика Вектора в шапке: человеческим языком, что было за сутки."""
    a, hp = d.get("activity") or {}, d.get("honeypot") or {}
    al = d.get("alerts") or []
    if hp.get("honeytoken"):
        return ("Тревога! Кто-то пытался войти учёткой-приманкой. Её логин знает только "
                "дамп базы — похоже на утечку. Разобрал всё ниже.")
    if al:
        return ("Я кое-что нашёл: %d %s %s внимания. Собрал сразу под этим сообщением, "
                "с объяснением, что делать." % (len(al), _plural(len(al), "пункт", "пункта",
                                                                  "пунктов"),
                                                 _plural(len(al), "требует", "требуют",
                                                         "требуют")))
    hits = int(hp.get("audit_hits") or 0)
    scans = ("Сканеры заглянули в приманки %d %s — все получили бан на сутки."
             % (hits, _plural(hits, "раз", "раза", "раз"))) if hits else \
        "В приманки сегодня никто не стучался — редкая тишина."
    return ("Привет! Сутки прошли спокойно: %d %s, %d %s. %s Сервер в порядке."
            % (a.get("logins_ok", 0), _plural(a.get("logins_ok", 0), "вход", "входа", "входов"),
               a.get("grades", 0), _plural(a.get("grades", 0), "оценка", "оценки", "оценок"),
               scans))


def _hero(d: dict, ok: bool, has_mascot: bool) -> str:
    when = datetime.fromtimestamp(d["now"], _TZ)
    months = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря")
    date = "%d %s" % (when.day, months[when.month - 1])
    n = len(d.get("alerts") or [])
    pill_col = OK if ok else (BAD if (d.get("honeypot") or {}).get("honeytoken") else WARN)
    pill_txt = "Всё в порядке" if ok else "Требует внимания · %d" % n
    pulse = "pulse_ok" if ok else ("pulse_bad" if pill_col == BAD else "pulse_warn")
    mascot = ("<img src='cid:vector' width='76' height='72' alt='Вектор' "
              "class='gb-float' style='display:block;width:76px;height:72px;border:0;"
              "border-radius:14px'>") if has_mascot else \
        "<div style='font-size:44px;line-height:72px;width:76px;text-align:center'>🐯</div>"
    #Шапка — одна строка таблицы: текст слева, Вектор справа. Прежняя шапка с тигром во
    #весь рост занимала на телефоне целый экран до первой цифры.
    return (
        "<table role='presentation' width='100%%' cellspacing='0' cellpadding='0' "
        "style='background:%s;background-image:linear-gradient(135deg,%s 0%%,%s 60%%,%s 100%%);"
        "border-radius:20px;margin:0 0 10px'><tr>"
        "<td style='padding:16px 6px 16px 18px;vertical-align:middle'>"
        "<div style='font-size:10.5px;font-weight:800;letter-spacing:.18em;color:#BFEFF3'>"
        "GRADEBOOKAI · ВСГУТУ</div>"
        "<div class='gb-title' style='font-size:22px;font-weight:900;color:#ffffff;"
        "letter-spacing:-.01em;margin:4px 0 2px;line-height:1.15'>Сводка за %s</div>"
        "<div style='font-size:12.5px;color:#D4F2F5'>%s по времени колледжа · за сутки</div>"
        "<table role='presentation' cellspacing='0' cellpadding='0' style='margin-top:10px'>"
        "<tr><td class='gb-pill' style='background:#ffffff;border-radius:999px;"
        "padding:3px 11px 3px 3px'><table role='presentation' cellspacing='0' cellpadding='0'>"
        "<tr><td style='padding-right:6px'><img src='cid:%s' width='20' height='20' alt='' "
        "style='display:block;border:0'></td><td style='font-size:12.5px;font-weight:800;"
        "color:%s'>%s</td></tr></table></td></tr></table></td>"
        "<td width='96' style='width:96px;padding:12px 14px 12px 0;vertical-align:middle;"
        "text-align:right'><div style='display:inline-block;background:%s;border-radius:16px;"
        "padding:3px'>%s</div></td></tr></table>"
        "<div style='background:#ffffff;border:1px solid %s;border-radius:16px;"
        "padding:11px 14px;margin:0 0 12px;font-size:14px;line-height:1.5;color:%s'>"
        "<b style='color:%s'>Вектор:</b> %s</div>"
        % (ACCENT, DEEP, ACCENT, BRIGHT, _e(date), when.strftime("%H:%M"), pulse, pill_col,
           _e(pill_txt), HERO_PANEL, mascot, LINE, TEXT, ACCENT, _e(_vector_line(d))))


def _alerts_block(alerts: list) -> str:
    if not alerts:
        return ""
    items = "".join(
        "<tr><td style='vertical-align:top;padding:5px 8px 5px 0;font-size:14px'>⚠️</td>"
        "<td style='padding:5px 0;font-size:13.5px;line-height:1.45;color:%s'>%s</td></tr>"
        % (TEXT, _e(x)) for x in alerts)
    return ("<div class='gb-up gb-d1' style='background:#FFF7E8;border:1px solid #F3D49B;"
            "border-radius:18px;padding:13px 14px;margin:0 0 12px'>"
            "<table role='presentation' cellspacing='0' cellpadding='0'><tr>"
            "<td style='padding-right:8px'><img src='cid:pulse_warn' width='20' height='20' "
            "alt='' style='display:block;border:0'></td><td style='font-size:15px;"
            "font-weight:800;color:%s'>Требует внимания</td></tr></table>"
            "<table role='presentation' cellspacing='0' cellpadding='0' style='margin-top:4px'>"
            "%s</table></div>" % (WARN, items))


def _activity_block(a: dict, imgs: dict) -> str:
    if a.get("error"):
        return _card("Активность", "<div style='color:%s'>%s</div>" % (BAD, _e(a["error"])))
    prev = a.get("prev") or {}
    fails = int(a.get("logins_fail") or 0)
    tiles = _kpi_grid([
        _kpi("🔑", "входов", a.get("logins_ok", 0),
             "%s %s" % (a.get("logins_people", 0),
                        _plural(a.get("logins_people", 0), "человек", "человека", "человек")),
             _delta(a.get("logins_ok"), prev.get("logins_ok"))),
        _kpi("📝", "оценок", a.get("grades", 0), "занятий: %s" % a.get("lessons", 0),
             _delta(a.get("grades"), prev.get("grades"))),
        _kpi("💬", "сообщений", a.get("messages", 0), "в мессенджере",
             _delta(a.get("messages"), prev.get("messages"))),
        _kpi("🚫", "неудачных входов", fails,
             "похоже на подбор" if fails >= 30 else "в норме",
             _delta(fails, prev.get("logins_fail"), good_up=False),
             BAD if fails >= 30 else TEXT),
    ])
    roles = a.get("roles") or {}
    who = " · ".join("%s %s <b>%d</b>" % (ROLE_RU.get(r, ("👤", r))[0],
                                          _e(ROLE_RU.get(r, ("👤", r))[1]), n)
                     for r, n in sorted(roles.items(), key=lambda kv: -kv[1]))
    peak = a.get("peak_hour")
    peak_txt = (" · пик с %02d:00 до %02d:00" % (peak, (peak + 1) % 24)
                if peak is not None else "")
    body = (tiles
            + _sub("Входы за неделю")
            + _chart("chart_logins", "Входы за неделю",
                     _html_bars(a.get("week") or [], ACCENT), "chart_logins" in imgs)
            + "<div style='font-size:12.5px;line-height:1.6;color:%s;margin-top:8px'>%s%s"
              "<br>В системе: <b>%s</b> студентов · <b>%s</b> преподавателей · <b>%s</b> "
              "родителей · <b>%s</b> групп</div>"
            % (MUTED, who or "Входов за сутки не было", _e(peak_txt), a.get("students", 0),
               a.get("teachers", 0), a.get("parents", 0), a.get("groups", 0)))
    return _card("Активность за сутки", body, icon="📈", delay=2)


def _line_item(left_html: str, n: int, hint: str = "", color: str = MUTED) -> str:
    """Одна строка списка: слева название, справа счёт, ниже — пояснение мелко."""
    return ("<div style='padding:7px 0;border-top:1px solid %s'><table role='presentation' "
            "width='100%%' cellspacing='0' cellpadding='0'><tr><td style='font-size:13.5px;"
            "color:%s'>%s</td><td style='font-size:13.5px;font-weight:800;color:%s;"
            "text-align:right;white-space:nowrap;padding-left:8px'>×%d</td></tr></table>%s</div>"
            % (LINE, TEXT, left_html, color, n,
               ("<div style='font-size:12px;color:%s;margin-top:2px'>%s</div>" % (MUTED, _e(hint)))
               if hint else ""))


def _honeypot_block(hp: dict, imgs: dict, site: str, bans: dict | None = None) -> str:
    radar = ("<img src='cid:radar' width='28' height='28' alt='' style='display:block;"
             "border:0;border-radius:50%'>") if "radar" in imgs else "📡"
    if hp.get("error"):
        return _card("Приманки", "<div style='color:%s'>%s</div>" % (BAD, _e(hp["error"])),
                     icon=radar)
    hits = int(hp.get("audit_hits") or 0)
    tiles = _kpi_grid([
        _kpi("🎯", "срабатываний", hits, "за сутки",
             _delta(hits, hp.get("prev_audit_hits"), good_up=False),
             BAD if hits else OK),
        _kpi("🛰", "источников", hp.get("sources", 0), "разных адресов"),
        _kpi("🌍", "стран", hp.get("countries", 0), "по базе iptoasn"),
        _kpi("⛔", "в бане сейчас", hp.get("banned_now", 0),
             "%d отказов после бана" % hp.get("after_ban", 0)),
    ])
    body = [tiles]
    bans = bans or {}
    if bans.get("week") is not None:
        #Баны сканеров на 80/443 по журналу Caddy (fail2ban): сутки за первый запрос к
        #.php и подобному, неделя — тем, кто вернулся (server/deploy/infra).
        body.append("<div style='font-size:12.5px;color:%s;margin-top:8px'>⛔ Сканеров в бане: "
                    "на неделю (вернулись) <b style='color:%s'>%d</b> · на сутки %s</div>"
                    % (MUTED, TEXT, bans["week"],
                       "?" if bans.get("day") is None else bans["day"]))
    if hp.get("honeytoken"):
        body.append("<div style='background:#FBE7E4;border:1px solid #F0B7AF;border-radius:14px;"
                    "padding:12px 14px;margin-top:12px;font-size:13.5px;color:%s'><b>🍯 Вход "
                    "учёткой-приманкой: %d.</b> Её логин есть только в дампе базы или файле "
                    "окружения — проверьте, откуда могла утечь копия.</div>"
                    % (BAD, hp["honeytoken"]))
    body.append(_sub("Срабатывания за неделю"))
    body.append(_chart("chart_honeypot", "Срабатывания приманок за неделю",
                       _html_bars(hp.get("week") or [], BAD), "chart_honeypot" in imgs))
    #«Откуда» — страна и провайдер одной строкой: два отдельных списка повторяли друг
    #друга (облако Google — это и США, и Google) и удваивали длину письма.
    #Списки по три: длинные хвосты — в разделе «Приманки», письмо читают с телефона.
    providers = (hp.get("top_providers") or [])[:3]
    if providers:
        body.append(_sub("Откуда"))
        for p in providers:
            badge = (" <span style='background:#E6F3F5;color:%s;border-radius:6px;"
                     "padding:1px 6px;font-size:10px;font-weight:800'>ОБЛАКО</span>" % ACCENT) \
                if is_cloud(p["name"]) else ""
            body.append(_meter("%s %s · <span style='color:%s'>%s</span>%s"
                               % (_flag(p["country"]), _e(country_name(p["country"])), MUTED,
                                  _e(p["name"][:38]), badge),
                               p["n"], providers[0]["n"], ACCENT))
    elif hp.get("top_countries"):
        body.append(_sub("Откуда"))
        peak = hp["top_countries"][0][1]
        body.extend(_meter("%s %s" % (_flag(cc), _e(country_name(cc))), n, peak, ACCENT)
                    for cc, n in hp["top_countries"][:3])
    tools = (hp.get("top_tools") or [])[:2]
    if tools:
        body.append(_sub("Чем стучались"))
        body.extend(_line_item("<b>%s</b> <span style='font-size:11px;color:%s'>· %s</span>"
                               % (_e(t["tool"][:36]), KIND_COLOR.get(t["kind"], MUTED),
                                  _e(KIND_LABELS.get(t["kind"], ""))),
                               t["n"], tool_hint(t["tool"], t["kind"]),
                               KIND_COLOR.get(t["kind"], MUTED)) for t in tools)
    paths = (hp.get("top_paths") or [])[:3]
    if paths:
        body.append(_sub("Что искали"))
        body.extend(_line_item("<span style='background:%s;color:#E9FBFD;font-family:Consolas,"
                               "Menlo,monospace;font-size:12px;border-radius:7px;"
                               "padding:2px 8px;word-break:break-all'>%s</span>"
                               % (DEEP, _e(path[:60])),
                               n, path_hint(path), TEXT) for path, n in paths)
    #«Самые настойчивые» (отпечатки источников) из письма убраны 27.10.2026: строка
    #`h:…` человеку в письме ничего не говорит, а место занимала. Они — в разделе.
    body.append(
        "<div style='margin-top:10px;font-size:13px'><a class='gb-btn' href='%s/admin/honeypot' "
        "style='color:%s;font-weight:700;text-decoration:none'>Адреса и подробности — в "
        "разделе «Приманки» →</a></div>" % (_e(site), ACCENT))
    return _card("Приманки", "".join(body), icon=radar,
                 sub="Кто стучался туда, куда не ходит никто законный", delay=3)


def _uptime_row(av: dict) -> str:
    """Доступность за 30 дней по минутным проверкам сторожа тревог."""
    if not av.get("known"):
        return ""
    pct = av["pct"]
    since = "" if av.get("days", 0) >= 30 else " (с %s.%s)" % (av["since"][8:10],
                                                             av["since"][5:7])
    return _status_row("📈 Доступность за 30 дней%s" % since,
                       "%s %% · простой %d мин" % (("%.2f" % pct).replace(".", ","),
                                                   av.get("down_min", 0)),
                       "ok" if pct >= 99.5 else ("warn" if pct >= 98 else "bad"))


def _ops_rows(ops: dict) -> list:
    """Копия на ПК, учения восстановления, обновление ОС — итоги ночных задач (`_ops`)."""
    from .nightly_report import DRILL_MAX_AGE_D, OFFSITE_MAX_AGE_D
    if not ops or ops.get("error"):
        return []
    rows = []
    off = ops.get("offsite") or {}
    rows.append(_status_row(
        "🏠 Копия базы на ПК",
        ("забрана " + _ago(off["age_d"])) if off.get("known")
        else "ещё не забиралась",
        "ok" if off.get("known") and off["age_d"] <= OFFSITE_MAX_AGE_D else "warn"))
    drill = ops.get("drill") or {}
    if drill.get("known"):
        value = ("копия поднялась за %s с · %s" % (drill.get("boot_s", "?"),
                                                  _ago(drill["age_d"]))
                 if drill.get("ok") else "не прошли")
        state = "bad" if not drill.get("ok") else (
            "warn" if drill["age_d"] > DRILL_MAX_AGE_D else "ok")
    else:
        value, state = "ещё не было", "warn"
    rows.append(_status_row("🧪 Учения восстановления", value, state))
    if not drill.get("ok") and drill.get("detail"):
        rows.append(_status_note(drill["detail"]))
    upd = ops.get("os_update") or {}
    if upd.get("known"):
        rows.append(_status_row(
            "🔄 Обновление ОС за неделю",
            ("пакетов %d%s" % (upd.get("count", 0), " · перезагрузка" if upd.get("reboot") else ""))
            if upd.get("ok") else "не прошло",
            "ok" if upd.get("ok") else "bad"))
        if not upd.get("ok") and upd.get("error"):
            rows.append(_status_note(upd["error"]))
    return rows


def _ago(age_d: float) -> str:
    """«сегодня», «вчера», «3 дн. назад» — по возрасту в сутках."""
    if age_d < 1:
        return "сегодня"
    return "вчера" if age_d < 2 else "%d дн. назад" % age_d


def _server_block(s: dict, imgs: dict, avail: dict | None = None,
                  ops: dict | None = None) -> str:
    from .nightly_report import BACKUP_MAX_AGE_H, CERT_MIN_DAYS
    if s.get("error"):
        return _card("Сервер", "<div style='color:%s'>%s</div>" % (BAD, _e(s["error"])))
    gauges = gauge_values(s)
    labels = "".join(
        "<td style='width:33%%;text-align:center;font-size:12px;color:%s'>"
        "<b style='color:%s'>%s</b><br>%s</td>" % (MUTED, TEXT, _e(g["label"]), _e(g["note"]))
        for g in gauges)
    if "chart_gauges" in imgs:
        rings = (_chart("chart_gauges", "Диск, память, нагрузка", "", True)
                 + "<table role='presentation' width='100%%' cellspacing='0' cellpadding='0'>"
                   "<tr>%s</tr></table>" % labels)
    else:
        rings = ("<table role='presentation' width='100%%' cellspacing='0' cellpadding='0'><tr>"
                 "%s</tr></table>" % "".join(
                     "<td style='width:33%%;text-align:center;padding:6px'><div style='"
                     "font-size:24px;font-weight:900;color:%s'>%d%%</div><div style='"
                     "font-size:12px;color:%s'><b style='color:%s'>%s</b><br>%s</div></td>"
                     % (g["color"], g["pct"], MUTED, TEXT, _e(g["label"]), _e(g["note"]))
                     for g in gauges))
    site, b, ssh = s.get("site") or {}, s.get("backup") or {}, s.get("ssh") or {}
    services = s.get("services") or {}
    down = [k for k, v in services.items() if v not in ("active", "?")]
    geo = s.get("ipgeo") or {}
    chain = s.get("audit_chain")
    #Шесть строк — то, что надо увидеть каждый вечер; мелочи (аптайм, база стран, своп) —
    #одной строкой ниже. Списком, а не плитками: плитки на телефоне шли по одной.
    rows = [
        _status_row("🌐 Сайт снаружи", ("отвечает за %s мс" % site.get("ms"))
                    if site.get("code") == 200 else "не отвечает (%s)" % (site.get("code") or
                                                                          site.get("error")),
                    "ok" if site.get("code") == 200 else "bad", first=True),
        _uptime_row(avail or {}),
        _status_row("⚙️ Службы", "все работают" if not down else "стоит: " + ", ".join(down),
                    "bad" if down else "ok"),
        _status_row("💾 Копия базы",
                    ("%s ч назад · копий %s" % (b.get("age_h"), b.get("count")))
                    if b.get("count") else ("копий нет" if b.get("known") else "не проверено"),
                    "bad" if (b.get("age_h") or 0) > BACKUP_MAX_AGE_H or
                    "FAIL" in (b.get("last_log") or "") else "ok"),
        *_ops_rows(ops or {}),
        _status_row("🔗 Журнал безопасности",
                    "цепочка сходится" if chain == "ok" else str(chain),
                    "ok" if chain in ("ok", "legacy") else "bad"),
        _status_row("🔒 Сертификат HTTPS",
                    ("ещё %d дн." % s["cert_days"]) if s.get("cert_days") is not None
                    else "не проверено",
                    "bad" if s.get("cert_days") is not None and s["cert_days"] < CERT_MIN_DAYS
                    else "ok"),
        _status_row("🧱 Подбор SSH за сутки",
                    ("%s попыток · в бане %s" % (ssh.get("failed", "?"),
                                                 ssh.get("f2b_banned", "?")))
                    if ssh else "не проверено", "ok"),
    ]
    extras = "Аптайм %s · база %s, %s · своп %s · база стран %s%s" % (
        _dur(s.get("uptime")),
        ("%s МБ" % s["db_mb"]) if s.get("db_mb") is not None else "?",
        "зашифрована" if s.get("db_encrypted") else "НЕ ЗАШИФРОВАНА",
        _mb((s.get("memory") or {}).get("swap_used")),
        ("от %s" % geo.get("updated")) if geo.get("available") else "не загружена",
        " · ⚠️ просит перезагрузку" if s.get("reboot_required") else "")
    body = (rings + "<div style='margin-top:8px'>%s</div>" % _status_table(rows)
            + "<div style='font-size:11.5px;line-height:1.5;color:%s;margin-top:6px'>%s</div>"
            % (MUTED, _e(extras)))
    return _card("Состояние сервера", body, icon="🖥", delay=3)


def gauge_values(s: dict) -> list:
    """Три кольца: диск, память, нагрузка. Цвет — по порогам, а не для красоты."""
    from .nightly_report import DISK_MIN_FREE_PCT, MEM_MIN_AVAIL_MB
    disk, mem = s.get("disk") or {}, s.get("memory") or {}
    out = []
    if disk.get("total"):
        used = 100.0 * (disk["total"] - disk.get("free", 0)) / disk["total"]
        state = "bad" if 100 - used < DISK_MIN_FREE_PCT else ("warn" if used > 75 else "ok")
        out.append({"label": "Диск", "pct": round(used), "state": state,
                    "note": "%s свободно" % _mb(disk.get("free"))})
    else:
        out.append({"label": "Диск", "pct": 0, "state": "?", "note": "не проверено"})
    if mem.get("total"):
        used = 100.0 * (mem["total"] - mem.get("available", 0)) / mem["total"]
        low = mem.get("available", 0) / 2 ** 20 < MEM_MIN_AVAIL_MB
        state = "bad" if low else ("warn" if used > 80 else "ok")
        out.append({"label": "Память", "pct": round(used), "state": state,
                    "note": "%s доступно" % _mb(mem.get("available"))})
    else:
        out.append({"label": "Память", "pct": 0, "state": "?", "note": "не проверено"})
    load = (s.get("load") or [0])[0] if s.get("load") else 0
    cpus = s.get("cpu_count") or 1
    pct = min(100, round(100.0 * load / cpus))
    out.append({"label": "Нагрузка", "pct": pct,
                "state": "bad" if pct > 90 else ("warn" if pct > 60 else "ok"),
                "note": "%.2f на %d %s" % (load, cpus, _plural(cpus, "ядро", "ядра", "ядер"))})
    for g in out:
        g["color"] = {"ok": OK, "warn": WARN, "bad": BAD}.get(g["state"], MUTED)
    return out


def _fact_block(now: float) -> str:
    title, text = fact_of_the_day(now)
    return ("<div class='gb-up gb-d5' style='background:%s;background-image:linear-gradient("
            "135deg,#F0FAFB,#E3F4F6);border:1px solid #CBE9ED;border-radius:18px;"
            "padding:13px 15px;margin:0 0 12px'><div style='font-size:10.5px;font-weight:800;"
            "letter-spacing:.14em;color:%s'>💡 ВЕКТОР ОБЪЯСНЯЕТ</div><div style='font-size:15px;"
            "font-weight:800;color:%s;margin:4px 0'>%s</div><div style='font-size:13.5px;"
            "line-height:1.5;color:%s'>%s</div></div>"
            % ("#EEF8F9", ACCENT, TEXT, _e(title), TEXT, _e(text)))


_STYLE_LAYOUT = """
<style>
  body,table,td,div{-webkit-text-size-adjust:100%;}
  a{color:#147C8B;}
  @media (max-width:520px){
    .gb-wrap{padding:10px 8px !important;}
    .gb-title{font-size:20px !important;}
  }
</style>"""

#⚠️ ОТДЕЛЬНЫЙ блок: клиент, не понимающий `@keyframes`, может выбросить блок целиком —
#пусть он выбросит только анимации, а не адаптивную раскладку.
_STYLE_MOTION = """
<style>
  @keyframes gbUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
  @keyframes gbFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
  @keyframes gbGrow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
  @keyframes gbRise{from{transform:scaleY(0)}to{transform:scaleY(1)}}
  @keyframes gbGlow{0%,100%{box-shadow:0 0 0 0 rgba(255,255,255,.55)}50%{box-shadow:0 0 0 7px rgba(255,255,255,0)}}
  .gb-up{animation:gbUp .8s cubic-bezier(.2,.8,.2,1) both;}
  .gb-d1{animation-delay:.05s}.gb-d2{animation-delay:.15s}.gb-d3{animation-delay:.25s}
  .gb-d4{animation-delay:.35s}.gb-d5{animation-delay:.45s}
  .gb-float{animation:gbFloat 3.4s ease-in-out infinite;}
  .gb-bar{transform-origin:left center;animation:gbGrow 1.2s cubic-bezier(.2,.8,.2,1) both;}
  .gb-rise{transform-origin:bottom center;animation:gbRise 1s cubic-bezier(.2,.8,.2,1) both;}
  .gb-pill{animation:gbGlow 2.6s ease-in-out infinite;}
  .gb-btn:hover{filter:brightness(1.1);}
  @media (prefers-reduced-motion:reduce){
    .gb-up,.gb-float,.gb-bar,.gb-rise,.gb-pill{animation:none !important;}
  }
</style>"""


def _images(d: dict) -> dict:
    """{cid: (байты, подтип)} — всё, что вкладывается в письмо."""
    from . import report_charts
    imgs: dict = {}
    ok = not d.get("alerts")
    for cid, name in (("vector", "vector_wave.gif" if ok else "vector_think.gif"),
                      ("radar", "radar.gif"), ("pulse_ok", "pulse_ok.gif"),
                      ("pulse_warn", "pulse_warn.gif"), ("pulse_bad", "pulse_bad.gif")):
        data = _asset(name)
        if data:
            imgs[cid] = (data, "gif")
    a, hp, s = d.get("activity") or {}, d.get("honeypot") or {}, d.get("server") or {}
    try:
        if a.get("week"):
            g = report_charts.bars(a["week"], ACCENT)
            if g:
                imgs["chart_logins"] = (g, "gif")
        if hp.get("week"):
            g = report_charts.bars(hp["week"], BAD)
            if g:
                imgs["chart_honeypot"] = (g, "gif")
        if not s.get("error"):
            g = report_charts.gauges(gauge_values(s))
            if g:
                imgs["chart_gauges"] = (g, "gif")
    except Exception as e:      # noqa: BLE001 — без графиков письмо всё равно уходит
        print("[report] графики не нарисовались: %s" % e)
    return imgs


def _security_block(sec: dict) -> str:
    """Защита: уязвимости и автообновления (`vuln_watch`) и тревоги за сутки (`alarm`)."""
    from . import vuln_watch
    al = sec.get("alarms") or {}
    if not sec.get("known") and not al.get("known"):
        return ""
    rows = []
    if sec.get("known"):
        opens = sec.get("open") or []
        bad = any(v.get("kev") for v in opens)
        checked = sec.get("checked_python")
        rows.append(_status_row("🔍 Пакеты Python сервера",
                                ("проверено %s · " % checked if checked else "")
                                + ("дыр нет" if not opens else "дыр %d" % len(opens)),
                                "bad" if bad else ("warn" if opens else "ok"), first=True))
        rows.extend(_status_note("%s%s %s — %s: %s" % (
            "в атаках (CISA KEV) · " if v.get("kev") else "", v.get("package"), v.get("version"),
            v.get("id"), ("исправление %s" % v["fixed"]) if v.get("fixed")
            else "исправления пока нет")) for v in opens)
        #Свежие эксплойты мира: письмо показывает, что проверка шла, а не только её итог
        #(«дыр нет» читалось как «ничего не делали», 27.10.2026).
        week = sec.get("kev_week") or []
        ours = [v for v in week if v.get("ours")]
        hit = [v for v in ours if v.get("verdict") in ("exposed", "nofix")]
        if sec.get("kev_total"):
            #Цвет — по вердикту для нашей машины, а не по совпадению названия продукта.
            calm = all(v.get("verdict") == "safe" for v in ours)
            rows.append(_status_row("🌍 Новые эксплойты в мире за неделю",
                                    "%d · наш стек: %d · задевает: %d"
                                    % (len(week), len(ours), len(hit)),
                                    "bad" if hit else ("ok" if calm else "warn")))
            rows.extend(_status_note("наш стек · %s — %s: %s" % (
                v["product"], v["cve"], vuln_watch.verdict_line(v))) for v in ours[:4])
            others = [v for v in week if not v.get("ours")][:3]
            if others:
                rows.append(_status_note("не наш стек: " + "; ".join(
                    v["product"] for v in others) + (" и ещё %d" % (len(week) - len(ours) - 3)
                                                    if len(week) - len(ours) > 3 else "")))
        acts = sec.get("actions") or []
        rows.append(_status_row("🔄 Автообновления за сутки",
                                "не понадобились" if not acts else "поставлено %d" % len(acts),
                                "bad" if any(not h.get("ok") for h in acts) else "ok"))
        rows.extend(_status_note("%s %s: %s" % ("✓" if h.get("ok") else "сбой:",
                                               "Python" if h.get("kind") == "python"
                                               else "ОС и Caddy", h.get("detail")))
                    for h in acts)
    if al.get("known"):
        recent = al.get("recent") or []
        rows.append(_status_row("🚨 Тревоги за сутки",
                                "не было" if not recent else "%d" % len(recent),
                                "warn" if recent else "ok", first=not rows))
        rows.extend(_status_note("%s · %s%s" % (
            datetime.fromtimestamp(h["ts"], _TZ).strftime("%H:%M"), h.get("title"),
            "" if h.get("sent") else " (письмо не ушло: %s)" % (h.get("skipped") or "сбой почты")))
            for h in recent[-6:])
        from .nightly_report import ALARM_MAX_SILENCE_MIN
        age = al.get("heartbeat_age_min")
        alive = age is not None and age <= ALARM_MAX_SILENCE_MIN
        rows.append(_status_row("👁 Сторож тревог", "на связи" if alive else "молчит",
                                "ok" if alive else "bad"))
    sub = "уязвимости — раз в час по OSV и CISA KEV · о взломе и падениях — письмом сразу"
    return _card("Защита", _status_table(rows), icon="🛡", sub=sub, delay=4)


def render_html(d: dict) -> tuple:
    """(html, inline) — страница письма и вложенные картинки `[(cid, байты, подтип)]`."""
    from . import config
    imgs = _images(d)
    a, hp, s = d.get("activity") or {}, d.get("honeypot") or {}, d.get("server") or {}
    ok = not d.get("alerts")
    site = (config.SITE_URL or "https://esstu-gradebook.ru").rstrip("/")
    preheader = ("%s · %s входов · приманки: %s · сайт %s" % (
        "всё в порядке" if ok else "требует внимания: %d" % len(d.get("alerts") or []),
        a.get("logins_ok", 0), hp.get("audit_hits", 0),
        "отвечает" if (s.get("site") or {}).get("code") == 200 else "не отвечает"))
    body = "".join((
        _hero(d, ok, "vector" in imgs),
        _alerts_block(d.get("alerts") or []),
        #Сначала то, где может быть беда (сервер, защита), приманки — ближе к концу: это
        #самый длинный и самый спокойный раздел.
        _activity_block(a, imgs),
        _server_block(s, imgs, ((d.get("security") or {}).get("alarms") or {})
                      .get("availability"), d.get("ops") or {}),
        _security_block(d.get("security") or {}),
        _honeypot_block(hp, imgs, site, (d.get("ops") or {}).get("bans")),
        _fact_block(d["now"]),
        "<div style='text-align:center;padding:4px 10px 2px'>"
        "<a href='%s' style='color:%s;font-size:13px;font-weight:700;text-decoration:none;"
        "margin:0 8px'>Сайт</a><a href='%s/admin/honeypot' style='color:%s;font-size:13px;"
        "font-weight:700;text-decoration:none;margin:0 8px'>Приманки</a>"
        "<a href='%s/admin/audit' style='color:%s;font-size:13px;font-weight:700;"
        "text-decoration:none;margin:0 8px'>Журнал</a><a href='%s/admin/server' style='"
        "color:%s;font-size:13px;font-weight:700;text-decoration:none;margin:0 8px'>Сервер</a>"
        "<div style='font-size:11.5px;line-height:1.5;color:%s;margin:12px auto 0;"
        "max-width:460px'>Только агрегированные числа: IP-адресов, логинов и ФИО в письме нет "
        "— оно хранится у почтового сервиса. Сводку собирает сервер сам каждый день в 17:00 "
        "по времени колледжа, о взломе и падениях пишет сразу.</div></div>"
        % (_e(site), ACCENT, _e(site), ACCENT, _e(site), ACCENT, _e(site), ACCENT, MUTED),
    ))
    #⚠️ Стили приклеиваются СНАРУЖИ форматирования: в них полно `%` (`100%`, `0%,100%`),
    #и оператор `%` принял бы их за подстановки.
    head = ("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='color-scheme' content='light'><meta name='supported-color-schemes' "
            "content='light'><title>Вечерняя сводка GradeBookAI</title>"
            + _STYLE_LAYOUT + _STYLE_MOTION + "</head>")
    page = head + ("<body class='gb-page' style='margin:0;padding:0;background:%s'>"
            #Прехедер: строка-превью в списке писем. Невидима в самом письме.
            "<div style='display:none;max-height:0;overflow:hidden;opacity:0;color:transparent'>"
            "%s</div><div class='gb-page' style='background:%s'><div class='gb-wrap' "
            "style='max-width:640px;margin:0 auto;padding:22px 14px;font-family:-apple-system,"
            "Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:%s'>%s</div></div></body></html>"
            % (PAGE, _e(preheader), PAGE, TEXT, body))
    #Вкладываем только то, на что письмо ссылается: три пульса нужны по одному.
    inline = [(cid, data, sub) for cid, (data, sub) in imgs.items() if "cid:" + cid in page]
    return page, inline


def render_text(d: dict) -> str:
    a, hp, s = d.get("activity") or {}, d.get("honeypot") or {}, d.get("server") or {}
    lines = ["GradeBookAI — вечерняя сводка (%s, Иркутск)"
             % datetime.fromtimestamp(d["now"], _TZ).strftime("%d.%m.%Y %H:%M"), "",
             "Вектор: " + _vector_line(d), ""]
    if d.get("alerts"):
        lines += ["ТРЕБУЕТ ВНИМАНИЯ:"] + ["  • " + x for x in d["alerts"]] + [""]
    lines.append("Активность: входов %s (%s чел.), оценок %s, сообщений %s, неудачных входов %s"
                 % (a.get("logins_ok"), a.get("logins_people"), a.get("grades"),
                    a.get("messages"), a.get("logins_fail")))
    lines.append("Приманки: срабатываний %s, источников %s, стран %s, забанено %s"
                 % (hp.get("audit_hits"), hp.get("sources"), hp.get("countries"),
                    hp.get("banned_now")))
    for path, n in (hp.get("top_paths") or [])[:5]:
        lines.append("  %s ×%d — %s" % (path, n, path_hint(path)))
    disk = s.get("disk") or {}
    lines.append("Сервер: диск свободно %s из %s, сайт %s, журнал %s"
                 % (_mb(disk.get("free")), _mb(disk.get("total")),
                    (s.get("site") or {}).get("code"), s.get("audit_chain")))
    sec = d.get("security") or {}
    if sec.get("known"):
        lines.append("Защита: открытых дыр %d, действий за сутки %d"
                     % (len(sec.get("open") or []), len(sec.get("actions") or [])))
        lines += ["  %s %s" % ("ok" if h.get("ok") else "СБОЙ", h.get("detail"))
                  for h in sec.get("actions") or []]
        if sec.get("checked_python"):
            lines.append("  пакетов Python проверено: %s" % sec["checked_python"])
        week = sec.get("kev_week") or []
        if sec.get("kev_total"):
            from . import vuln_watch
            lines.append("  новых эксплойтов в мире за неделю: %d, наш стек: %d"
                         % (len(week), sum(1 for v in week if v.get("ours"))))
            lines += ["    %s — %s: %s" % (v["product"], v["cve"], vuln_watch.verdict_line(v))
                      for v in week if v.get("ours")][:4]
    al = sec.get("alarms") or {}
    av = al.get("availability") or {}
    if av.get("known"):
        lines.append("Доступность за 30 дней: %s %%, простой %d мин"
                     % (("%.2f" % av["pct"]).replace(".", ","), av.get("down_min", 0)))
    ops = d.get("ops") or {}
    if ops and not ops.get("error"):
        off, drill, upd = (ops.get(k) or {} for k in ("offsite", "drill", "os_update"))
        lines.append("Копия на ПК: %s" % (_ago(off["age_d"]) if off.get("known")
                                          else "ещё не забиралась"))
        lines.append("Учения восстановления: %s" % (
            ("прошли " + _ago(drill["age_d"])) if drill.get("ok")
            else ("НЕ ПРОШЛИ: %s" % drill.get("detail")) if drill.get("known") else "ещё не было"))
        if upd.get("known"):
            lines.append("Обновление ОС: %s" % ("пакетов %d" % upd.get("count", 0)
                                                if upd.get("ok") else "СБОЙ: %s" % upd.get("error")))
        bans = ops.get("bans") or {}
        if bans.get("week") is not None:
            lines.append("Сканеры в бане: на неделю %d, на сутки %s"
                         % (bans["week"], bans.get("day")))
    if al.get("known"):
        lines.append("Тревоги за сутки: %d" % len(al.get("recent") or []))
        lines += ["  %s %s" % (datetime.fromtimestamp(h["ts"], _TZ).strftime("%H:%M"),
                               h.get("title")) for h in (al.get("recent") or [])[-6:]]
    title, text = fact_of_the_day(d["now"])
    lines += ["", "Вектор объясняет — %s: %s" % (title, text), "",
              "Только агрегированные числа: персональных данных в письме нет."]
    return "\n".join(lines)


def subject(d: dict) -> str:
    day = datetime.fromtimestamp(d["now"], _TZ).strftime("%d.%m")
    n = len(d.get("alerts") or [])
    if (d.get("honeypot") or {}).get("honeytoken"):
        return "🍯 GradeBookAI · %s — вход учёткой-приманкой!" % day
    tail = "✅ всё в порядке" if not n else "⚠️ требует внимания: %d" % n
    return "GradeBookAI · сводка за %s — %s" % (day, tail)
