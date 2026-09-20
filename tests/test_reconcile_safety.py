"""
test_reconcile_safety.py — сверка «сервер = истина» не стирает то, чего сервер не
подтвердил (находка ревью J04, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`reconcile` спасал офлайн-правки пушем и стирал локальный кэш, проверяя РОВНО ОДНО
условие — не бросил ли push исключение. А успешный ответ у отправки бывает трёх сортов,
и два из них означают, что правок на сервере НЕТ:

• **собрали не всё.** Коллектор при сбое чтения таблицы отдаёт пустой список и ставит
  `collect_failed` — ронять весь цикл из-за одной залоченной таблицы нельзя. Но пустота
  неотличима от «изменений нет»: push проходит, сервер этих строк не видел никогда, и
  следом они стираются с единственной машины, где лежали;
• **сервер часть отверг** (`rejected`). Случай штатный и живой: админ снял назначение
  преподавателя на предмет, пока тот работал офлайн. Ответ при этом успешный.

Третья беда шла следом: очистка выполнялась ДО того, как новый снимок получен. Оборвался
pull — человек оставался с пустым журналом, и докстринг предупреждал об этом словами
«останется пустая база», ничего не предлагая взамен.

⚠️ Почему у трёх бед три РАЗНЫХ ответа, а не один общий: сбой чтения временный (повтор
осмыслен → исключение, флаг сверки не снимается), отказ сервера стойкий (повтор дал бы
тот же отказ каждые 30 с полным снимком базы → обмен без очистки), обрыв pull уже
случился после очистки (→ откат к копии).

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН на каждой из трёх защит по отдельности.
"""
import pytest

from data import data_store
from data.core import DBManager
from data.data_store import get_store
from sync import sync_engine


def _seed():
    """Локальные данные, которые сверка обязана не потерять."""
    st = get_store()
    st.set_groups([{"name": "ИС-21", "subjects": ["Математика"]}])
    st.set_students([{"surname": "Петров", "name": "Пётр", "group": "ИС-21",
                      "login": "petrov", "password_hash": "h"}])
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO lessons (id,group_name,subject,updated_at,deleted) "
                "VALUES ('L1','ИС-21','Математика','2026-01-01T00:00:00+00:00',0)")
    cur.execute("INSERT OR REPLACE INTO grades (student_f,student_n,lesson_id,grade,"
                "updated_at,deleted) VALUES ('Петров','Пётр','L1','5',"
                "'2026-01-01T00:00:00+00:00',0)")
    conn.commit()
    conn.close()
    data_store.set_sync_watermark("2026-01-01T00:00:00+00:00")


def _grades() -> int:
    conn = DBManager.get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0]
    finally:
        conn.close()


class _Ok:
    """Сервер принимает всё и отдаёт пустой снимок (после очистки локаль осталась бы
    пустой — именно это и позволяет отличить «стёрли» от «не стирали»)."""

    def __init__(self, rejected=None):
        self.pushes = []
        self.pulls = 0
        self._rejected = rejected or {}

    def push(self, data):
        import copy
        self.pushes.append(copy.deepcopy(data))
        out = {"applied": {}}
        if self._rejected:
            out["rejected"] = dict(self._rejected)
        return out

    def pull(self, since=""):
        self.pulls += 1
        return {"server_time": "2026-02-02T00:00:00+00:00", "changes": {}}


def test_unread_tables_stop_the_wipe(fresh_db, monkeypatch):
    """Собрали не всё → сервер этих строк не видел → стирать нечего и незачем."""
    _seed()

    real = sync_engine.collect_local

    def _half_collected(since=""):
        out = real(since)
        sync_engine._session.collect_failed = True   #как делает упавший коллектор
        return out

    monkeypatch.setattr(sync_engine, "collect_local", _half_collected)
    client = _Ok()
    with pytest.raises(RuntimeError):
        sync_engine.reconcile(client)

    assert _grades() == 1, "кэш стёрт, хотя часть локальных таблиц не прочиталась"


def test_rejected_rows_stop_the_wipe_but_not_the_exchange(fresh_db):
    """Отказ сервера стойкий: кэш цел, обмен всё равно состоялся, исключения нет."""
    _seed()
    client = _Ok(rejected={"grades": 1})

    assert sync_engine.reconcile(client) is True

    assert _grades() == 1, "отвергнутая сервером оценка стёрта — она была только здесь"
    assert client.pulls >= 1, "обмен не выполнен: сверка вернула бы False у вызывающего"
    assert sync_engine._session.last_rejected == {"grades": 1}, \
        "отказ не виден ни в логе, ни в статусе — индикатору нечего показать"


def test_a_failed_pull_after_the_wipe_brings_the_data_back(fresh_db):
    """Кэш уже стёрт, снимок не доехал — база возвращается из копии, а не остаётся пустой."""
    _seed()

    class _PullDies(_Ok):
        def pull(self, since=""):
            self.pulls += 1
            raise RuntimeError("связь оборвалась на полном снимке")

    client = _PullDies()
    with pytest.raises(RuntimeError):
        sync_engine.reconcile(client)

    assert _grades() == 1, "после обрыва снимка человек остался с пустым журналом"


def test_a_clean_run_still_wipes_the_cache(fresh_db):
    """Обратная сторона: сверка обязана делать то, ради чего заведена."""
    _seed()
    client = _Ok()

    assert sync_engine.reconcile(client) is True

    assert _grades() == 0, "кэш не стёрт — осиротевшие записи так и останутся навсегда"
    assert client.pushes, "офлайн-правки не отправлены перед очисткой"


def test_wipe_is_skipped_when_no_snapshot_could_be_taken(fresh_db, monkeypatch):
    """Нет копии — нет отката. Стирать в этом состоянии нельзя: вернуть будет нечем."""
    _seed()
    monkeypatch.setattr(DBManager, "backup", classmethod(lambda cls, reason="": ""))
    client = _Ok()

    assert sync_engine.reconcile(client) is True
    assert _grades() == 1, "кэш стёрт без возможности отката"
