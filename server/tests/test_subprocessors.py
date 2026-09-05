"""
Сторож реестра субобработчиков (`docs/SUBPROCESSORS.md`).

На приёмке первый вопрос — не «как вы шифруете», а «КОМУ вы передаёте»: утечка
PowerSchool пришла через подрядчика. Плюс п. 5.6.1 политики ВСГУТУ прямо запрещает
трансграничную передачу ПДн.

⚠️ Обычный реестр — это текст, который пишут один раз и который расходится с кодом на
первом же новом сервисе. Расхождение здесь опаснее отсутствия: отсутствие означает «не
подготовили», расхождение — «предоставили недостоверные сведения оператору ПДн».

Поэтому проверяется СВЯЗЬ: каждый внешний адрес, записанный в коде литералом, обязан
быть описан в реестре. Список сервисов в тесте НЕ дублируется — иначе он краснел бы на
каждом законном добавлении и подталкивал «просто вписать хост в ожидание», то есть ровно
к тому, от чего защищает.
"""
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REGISTRY = os.path.join(ROOT, "docs", "SUBPROCESSORS.md")

#Каталоги продукта, которые реально ходят в сеть от имени сервера ИЛИ КЛИЕНТА.
#🔥 `web/src` и `web/public` ДОБАВЛЕНЫ 05.09.2026 после разбора Полковника. Их тут не
#было, и это делало проверку опасной: она молчала ровно про тот случай, ради которого
#заведена. В `web/src/utils/videoEmbed.js` лежат встраивания YouTube, VK и Rutube —
#браузер студента грузит iframe с youtube.com, то есть с сервера Google LLC, той самой
#компании, которую мы убрали из перевода по п. 5.6.1. В реестре их не было, а сторож
#был зелёным и остался бы зелёным при добавлении любого нового хоста во фронт.
#⚠️ Урок общий: **проверка, охватывающая только половину продукта, выдаёт частичный
#ответ за полный.** Тот же класс, что `validate-agents.py`, который разбирал frontmatter
#не так, как настоящий потребитель, и год отвечал «всё валидно».
SCAN_DIRS = ("server/app", "schedule", "data", "sync", "desktop",
             "web/src", "web/public")
SCAN_FILES = ("weather.py", "desktop_update.py", "vector_nlu.py", "support_kb.py")
#Расширения, в которых ищем. Клиент — это .js/.mjs/.vue/.html, а не только .py.
SCAN_SUFFIXES = (".py", ".js", ".mjs", ".vue", ".html")

#Что адресом субобработчика НЕ является. Каждый пункт с причиной — исключение без
#записанной причины это не исключение, а забытый случай (урок 02.09.2026, префикс
#"public/" в стороже маршрутов прикрывал настоящую дыру).
_OURS = {
    "esstu-gradebook.ru": "наш собственный домен",
    "localhost": "петля",
    "127.0.0.1": "петля",
    "0.0.0.0": "адрес прослушивания",
    "journal.vsgutu.ru": "запасное имя нашего же сайта",
    "example.com": "пример в документации",
    "evil.com": "выдуманный хост в тестах защиты от подмены origin",
    "127.0.0.1.evil.com": "то же — проверка, что суффикс не обманывает разбор",
    "schemas.microsoft.com": "пространство имён XML, обращения по нему нет",
    "www.w3.org": "пространство имён SVG/XML, обращения по нему нет",
    "schema.org": "пространство имён JSON-LD в разметке страницы; запроса туда нет",
    "192.168.0.101": "адрес машины разработчика в локальной сети, не боевой",
    #⚠️ Проверено чтением, а не отмахнулись: `web/src/utils/markdownLite.js:29` —
    #комментарий «смотри https://a.b.» в пояснении к обрезке висящей пунктуации.
    "a.b": "образец в комментарии к разбору автоссылок, не адрес",
}

_URL = re.compile(r"https?://([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)")


def _iter_sources():
    for rel in SCAN_DIRS:
        base = os.path.join(ROOT, rel)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", "tests", "node_modules")]
            for fn in filenames:
                if fn.endswith(SCAN_SUFFIXES):
                    yield os.path.join(dirpath, fn)
    for rel in SCAN_FILES:
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path):
            yield path


def _hosts_in_code() -> dict:
    """{хост: [файлы]} — все внешние адреса, записанные в коде литералом."""
    found: dict = {}
    for path in _iter_sources():
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for host in _URL.findall(text):
            host = host.lower().rstrip(".")
            if host in _OURS or not host:
                continue
            found.setdefault(host, []).append(os.path.relpath(path, ROOT))
    return found


@pytest.fixture(scope="module")
def registry_text():
    if not os.path.isfile(REGISTRY):
        pytest.fail("docs/SUBPROCESSORS.md отсутствует — реестра субобработчиков нет")
    with open(REGISTRY, encoding="utf-8") as fh:
        return fh.read().lower()


def test_every_outbound_host_is_registered(registry_text):
    """🔑 ГЛАВНОЕ СВОЙСТВО: сервис, появившийся в коде, обязан появиться в реестре."""
    unknown = {h: f for h, f in _hosts_in_code().items() if h not in registry_text}
    assert not unknown, (
        "продукт ходит на адреса, которых нет в docs/SUBPROCESSORS.md:\n" +
        "\n".join("  %s  <- %s" % (h, ", ".join(sorted(set(f))))
                  for h, f in sorted(unknown.items())) +
        "\nЛибо опиши сервис в реестре, либо убери обращение. Молча передавать "
        "данные третьей стороне нельзя: это п. 5.6.1 политики ВСГУТУ.")


def test_the_scan_actually_finds_something(registry_text):
    """Обратный ход самого сторожа: он обязан ЧТО-ТО находить.

    ⚠️ Без этой проверки достаточно опечатки в регулярке или в списке каталогов — и
    сторож станет зелёным навсегда, ничего не проверяя. Ровно так у нас четыре раза
    подряд зеленел `pollingRespectsVisibility` при сломанном продукте."""
    hosts = _hosts_in_code()
    assert len(hosts) >= 3, (
        "разбор нашёл почти ничего (%r) — скорее всего сломан он сам, а не продукт"
        % sorted(hosts))
    #Три заведомо живых обращения. Если хотя бы одно пропало из кода — это законное
    #изменение, но узнать о нём надо здесь, а не от покупателя.
    for host in ("api.open-meteo.com", "api.klipy.com", "portal.esstu.ru"):
        assert host in hosts, (
            "%s больше не встречается в коде. Если сервис убран — убери строку и из "
            "реестра, иначе документ обещает то, чего нет" % host)


def test_registry_names_the_only_place_where_real_personal_data_leaves(registry_text):
    """Реестр обязан отделять «уходит запрос» от «уходят ПДн».

    Строка про объектное хранилище — единственная, где наружу идут файлы людей. Свести
    её в общий список «третьи стороны» значило бы утопить единственный настоящий риск
    среди безобидных."""
    assert "s3" in registry_text, "в реестре нет строки про объектное хранилище вложений"
    assert "5.2.4.1" in registry_text, (
        "не назван пункт политики ВСГУТУ, который запрещает поручать обработку другому "
        "лицу — а именно он решает, где может стоять хранилище")


def test_registry_states_its_own_blind_spot(registry_text):
    """Документ обязан сам называть, чего он НЕ ловит.

    Хост из настройки (S3) и хост внутри чужой библиотеки (GigaChat SDK) проверкой не
    находятся. Умолчать об этом — значит выдать частичную проверку за полную; ровно так
    `.claude/validate-agents.py` год отвечал «все определения валидны», разбирая формат
    иначе, чем настоящий потребитель."""
    assert "литерал" in registry_text, (
        "в реестре не сказано, что проверка видит только адреса, записанные в коде "
        "литералом")
