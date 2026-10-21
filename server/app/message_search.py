"""
message_search.py — полнотекстовый поиск по сообщениям с ранжированием BM25 (20.10.2026).

Исследование «Высшая математика в журнале», п. 4.2. Что было и почему плохо:
поиск внутри беседы брал ПОСЛЕДНИЕ 2000 сообщений и искал подстроку в Python
(`.lower()` и `in`). Старое сообщение не находилось вовсе — и человеку об этом не
говорилось; порядок выдачи — просто «от новых к старым», без оценки, насколько
сообщение отвечает на запрос.

── КАК УСТРОЕНО ────────────────────────────────────────────────────────────────────
• Индекс — виртуальная таблица SQLite FTS5 `messages_fts` (тот же файл базы, то есть под
  тем же шифрованием SQLCipher: в открытый вид текст не выходит). Токенизатор `unicode61`
  складывает регистр, в том числе кириллицы (проверено на 3.45 и 3.51); «ё» мы приводим
  к «е» сами — и в индексе, и в запросе.
• Индекс ведут ТРИГГЕРЫ базы на вставку, правку текста/удаление и физическое удаление
  сообщения. Не код приложения — потому что сообщения пишутся из десятка мест (отправка,
  пересылка, системные, `/clear`, модерация), и «не забыть обновить индекс» в каждом —
  наш класс дефекта «первое забытое место». Триггер забыть нельзя.
• Ранжирование — BM25 (Стивен Робертсон, Карен Спэрк Джонс и коллеги, 1990-е; основа —
  обратная частота документа Спэрк Джонс, 1972). Принцип: слово весит тем больше, чем
  реже оно в переписке (IDF); повторы слова в сообщении дают убывающую добавку
  (насыщение k₁); длинное сообщение не выигрывает просто длиной (нормировка b). Это
  стандарт Lucene/Elasticsearch и встроенная функция FTS5 `bm25()`.
• Словоформы — отсечение окончаний по образцу стеммера Портера (Мартин Портер, 1980;
  русский вариант Snowball — 2001), упрощённое: «оценки», «оценкой», «оценок» → «оценк*».
  Префиксный запрос FTS5 находит все формы. Полный Snowball — сотни строк правил; для
  поиска в своей переписке хватает отсечения одного окончания.
• Кусок из середины слова («граммир» в «программирование», «ебра» в «зебра») — второй
  индекс на ТРИГРАММАХ (`messages_trgm`, 21.10.2026, разбор Ярослава по n-граммным
  индексам GitHub). Слово режется на перекрывающиеся тройки букв; фраза из троек найдётся
  только там, где они идут подряд, то есть где есть сама подстрока. Ищем `MATCH`, а не
  `LIKE`: индекс складывает регистр по Юникоду, а встроенный `LIKE` при перепроверке
  строки складывает только латиницу и отбрасывал бы «ПРОГРАММИРОВАНИЮ» на «граммир».
  Короче трёх букв фрагмент не ищется (триграмм в нём нет), такие слова ищет первый
  индекс. Цена — место: триграммный индекс крупнее текста в разы; на бою переписка
  невелика, на стенде с 922 тыс. сообщений это стоит замерить до выкладки.

── ГРАНИЦЫ ─────────────────────────────────────────────────────────────────────────
• Видимость решает НЕ индекс, а прежняя дверь `_visible_messages_query` (удалённое,
  «удалить у себя», очистка истории — инвариант §4.40): индекс только предлагает
  кандидатов, отбирает и сортирует их обычный запрос.
• Нет FTS5 в сборке SQLite — `available()` ложь, и поиск работает по-старому (громко в
  журнале, а не молча).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import text

log = logging.getLogger("gradebook.search")

#Сколько кандидатов берём из индекса до фильтра видимости. Больше, чем отдаёт ручка
#(100): часть кандидатов может оказаться скрытой у этого человека.
CANDIDATES = 500

_TRIGGERS = ("messages_fts_ai", "messages_fts_au", "messages_fts_ad",
             "messages_trgm_ai", "messages_trgm_au", "messages_trgm_ad")
#«ё» → «е» внутри базы: FTS5 сам этого не делает, а люди пишут то так, то так.
_FOLD_SQL = "replace(replace({0}, 'ё', 'е'), 'Ё', 'Е')"
_DDL = [
    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
    "body, conversation_id UNINDEXED, tokenize = 'unicode61 remove_diacritics 2')",
    "CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages "
    "WHEN new.deleted_at = '' AND new.kind = 'text' BEGIN "
    "INSERT INTO messages_fts(rowid, body, conversation_id) "
    f"VALUES (new.id, {_FOLD_SQL.format('new.body')}, new.conversation_id); END",
    "CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE OF body, deleted_at, kind "
    "ON messages BEGIN DELETE FROM messages_fts WHERE rowid = old.id; "
    "INSERT INTO messages_fts(rowid, body, conversation_id) "
    f"SELECT new.id, {_FOLD_SQL.format('new.body')}, new.conversation_id "
    "WHERE new.deleted_at = '' AND new.kind = 'text'; END",
    "CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN "
    "DELETE FROM messages_fts WHERE rowid = old.id; END",
    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_trgm USING fts5("
    "body, conversation_id UNINDEXED, tokenize = 'trigram remove_diacritics 1')",
    "CREATE TRIGGER IF NOT EXISTS messages_trgm_ai AFTER INSERT ON messages "
    "WHEN new.deleted_at = '' AND new.kind = 'text' BEGIN "
    "INSERT INTO messages_trgm(rowid, body, conversation_id) "
    f"VALUES (new.id, {_FOLD_SQL.format('new.body')}, new.conversation_id); END",
    "CREATE TRIGGER IF NOT EXISTS messages_trgm_au AFTER UPDATE OF body, deleted_at, kind "
    "ON messages BEGIN DELETE FROM messages_trgm WHERE rowid = old.id; "
    "INSERT INTO messages_trgm(rowid, body, conversation_id) "
    f"SELECT new.id, {_FOLD_SQL.format('new.body')}, new.conversation_id "
    "WHERE new.deleted_at = '' AND new.kind = 'text'; END",
    "CREATE TRIGGER IF NOT EXISTS messages_trgm_ad AFTER DELETE ON messages BEGIN "
    "DELETE FROM messages_trgm WHERE rowid = old.id; END",
]
_REBUILD = [
    "DELETE FROM messages_fts",
    "INSERT INTO messages_fts(rowid, body, conversation_id) "
    f"SELECT id, {_FOLD_SQL.format('body')}, conversation_id FROM messages "
    "WHERE deleted_at = '' AND kind = 'text'",
    "DELETE FROM messages_trgm",
    "INSERT INTO messages_trgm(rowid, body, conversation_id) "
    f"SELECT id, {_FOLD_SQL.format('body')}, conversation_id FROM messages "
    "WHERE deleted_at = '' AND kind = 'text'",
]

_state = {"available": None}


def ensure(conn) -> bool:
    """Завести индекс и триггеры, если их нет; при неполном индексе — пересобрать.

    Идемпотентно и дёшево, когда всё на месте (один запрос к `sqlite_master`). Пересборка
    нужна в двух случаях: первый запуск на базе с историей и пересозданная таблица
    `messages` (её удаление уносит триггеры, а индекс остаётся со старыми строками).
    Возвращает, работает ли полнотекстовый поиск."""
    if _state["available"] is False:
        return False
    try:
        have = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'messages_fts_%'"))}
        if set(_TRIGGERS) <= have:
            _state["available"] = True
            return True
        for stmt in _DDL:
            conn.execute(text(stmt))
        for stmt in _REBUILD:
            conn.execute(text(stmt))
        _state["available"] = True
        log.info("индекс поиска по сообщениям (FTS5) заведён и наполнен")
        return True
    except Exception as e:      # noqa: BLE001 — поиск обязан работать и без индекса
        #Навсегда (до перезапуска) выключаемся, только если FTS5 в сборке НЕТ. Разовый
        #сбой («database is locked» и т. п.) не повод терять поиск на весь день: в этот
        #раз ищем по-старому, в следующий попробуем снова.
        if "fts5" in str(e).lower():
            _state["available"] = False
        log.warning("полнотекстовый поиск недоступен, работаем по-старому: %s", e)
        return False


_WORD_RE = re.compile(r"\w+", re.UNICODE)
#Окончания по убыванию длины: первым снимается самое длинное подходящее.
_ENDINGS = sorted((
    "иями", "ями", "ами", "ией", "ием", "иях", "ого", "его", "ому", "ему", "ыми", "ими",
    "ых", "их", "ой", "ей", "ий", "ый", "ая", "яя", "ое", "ее", "ом", "ем", "ам", "ям",
    "ах", "ях", "ов", "ев", "ью", "ия", "ие", "ию", "ии", "а", "я", "о", "е", "и", "ы",
    "у", "ю", "ь", "й"), key=len, reverse=True)
#Основа короче этого не режется: «дз», «пара», «вчера» остаются словами целиком.
_MIN_STEM = 4


def stem(word: str) -> str:
    """Основа слова для префиксного запроса: снимается ОДНО окончание, основа ≥ 4 букв."""
    w = word.lower().replace("ё", "е")
    for end in _ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= _MIN_STEM:
            return w[: -len(end)]
    return w


def build_query(q: str) -> str:
    """Запрос FTS5 из того, что набрал человек: все слова обязательны, каждое — префиксом
    основы. Слова берутся в кавычки — так спецсимволы запроса (`"`, `*`, `NEAR`, `-`) не
    становятся синтаксисом FTS5, и «сломать» поиск строкой нельзя."""
    words = [stem(w) for w in _WORD_RE.findall(q or "")]
    return " ".join(f'"{w}"*' for w in words if w)


def fragment_query(q: str) -> str:
    """Запрос к триграммному индексу: каждое слово от трёх букв — фраза-подстрока, все
    обязательны. Кавычки внутри слова невозможны (слово — буквы и цифры по `_WORD_RE`),
    подчёркивание выбрасываем."""
    words = [w.replace("_", "").lower().replace("ё", "е") for w in _WORD_RE.findall(q or "")]
    return " AND ".join(f'"{w}"' for w in words if len(w) >= 3)


def candidate_ids(conn, conv_id: str, q: str, limit: int | None = None,
                  min_id: int = 0) -> list | None:
    """id сообщений беседы по запросу, лучшие по BM25 первыми (при равенстве — новее).
    None — индекс недоступен (вызывающий ищет по-старому); [] — ничего не нашлось.

    `min_id` — первое сообщение, которое человек вообще видит (после «очистить историю»
    это не начало беседы). Без него в большой беседе 500 лучших кандидатов могли целиком
    оказаться в очищенной старине, фильтр видимости их бы отбросил, и поиск вернул бы
    пустоту при живых совпадениях (нашёл Полковник 21.10.2026)."""
    match, fragment = build_query(q), fragment_query(q)
    if not match:
        return []
    #Индекс заводим ОТДЕЛЬНОЙ транзакцией движка: сессия GET-запроса не коммитится, и
    #созданные в ней триггеры откатились бы вместе с ней.
    from .db import engine
    with engine.begin() as ddl:
        ok = ensure(ddl)
    if not ok:
        return None
    n = int(limit or CANDIDATES)
    try:
        rows = conn.execute(text(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH :m "
            "AND conversation_id = :c AND rowid >= :lo "
            "ORDER BY bm25(messages_fts), rowid DESC LIMIT :n"),
            {"m": match, "c": conv_id, "lo": int(min_id or 0), "n": n}).fetchall()
        #Словами не нашлось достаточно — добираем кусками слов: сначала то, что совпало
        #словом (оно точнее), потом фрагменты, свежие первыми.
        extra = []
        if fragment and len(rows) < n:
            extra = conn.execute(text(
                "SELECT rowid FROM messages_trgm WHERE messages_trgm MATCH :m "
                "AND conversation_id = :c AND rowid >= :lo ORDER BY rowid DESC LIMIT :n"),
                {"m": fragment, "c": conv_id, "lo": int(min_id or 0), "n": n}).fetchall()
    except Exception as e:      # noqa: BLE001
        log.warning("запрос к индексу поиска не удался, ищем по-старому: %s", e)
        return None
    ids = [int(r[0]) for r in rows]
    seen = set(ids)
    ids += [int(r[0]) for r in extra if int(r[0]) not in seen]
    return ids[:n]
