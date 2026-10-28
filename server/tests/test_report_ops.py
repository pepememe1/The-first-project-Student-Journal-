"""Итоги ночного обслуживания в вечерней сводке: копия на ПК, учения, обновление ОС, баны.

Файлы состояния пишут скрипты deploy/backup и deploy/maintenance; здесь они подложены во
временный каталог, а fail2ban подменён."""
import json

import pytest

from app import nightly_report, report_mail

NOW = 1_793_200_000.0
DAY = 86400


@pytest.fixture()
def ops_dir(tmp_path, monkeypatch):
    files = {k: str(tmp_path / ("%s.json" % k)) for k in nightly_report.OPS_FILES}
    monkeypatch.setattr(nightly_report, "OPS_FILES", files)
    monkeypatch.setattr(nightly_report, "_run", lambda cmd, timeout=15: (
        "Status for the jail: %s\n|- Currently banned:\t%d\n" % (cmd[-1], 16 if "week" in
                                                                  cmd[-1] else 3)))

    def put(which, /, **st):
        with open(files[which], "w", encoding="utf-8") as fh:
            json.dump(st, fh)
    return put


def _alerts(ops):
    return nightly_report._ops_alerts(ops)


def test_everything_done_on_time_is_quiet_and_shown_in_the_letter(ops_dir):
    ops_dir("offsite", ts=NOW - DAY, name="gradebook_20261027.db")
    ops_dir("drill", ts=NOW - 2 * DAY, ok=True, detail="копия поднялась", boot_s="7")
    ops_dir("os_update", ts=NOW - 3 * DAY, ok=True, count=11, reboot=False, error="")
    ops = nightly_report._ops(NOW)
    assert _alerts(ops) == []
    assert ops["bans"] == {"day": 3, "week": 16}
    html = report_mail._server_block({}, {}, None, ops)
    assert "Копия базы на ПК" in html and "забрана вчера" in html
    assert "поднялась за 7 с · 2 дн. назад" in html and "пакетов 11" in html
    assert "на неделю (вернулись) <b" in report_mail._honeypot_block({}, {}, "", ops["bans"])
    text = report_mail.render_text({"now": NOW, "ops": ops})
    assert "Копия на ПК: вчера" in text and "на неделю 16" in text


def test_broken_promises_are_alerts(ops_dir):
    #Ничего ещё не было — это не «всё хорошо»: копии вне машины и учений нет.
    text = "\n".join(_alerts(nightly_report._ops(NOW)))
    assert "Копии базы вне сервера ещё нет" in text and "Учений восстановления ещё не было" in text

    ops_dir("offsite", ts=NOW - 8 * DAY, name="x.db")
    ops_dir("drill", ts=NOW - DAY, ok=False, detail="копия не поднялась за 90 с")
    ops_dir("os_update", ts=NOW - DAY, ok=False, count=0, error="dpkg прерван")
    text = "\n".join(_alerts(nightly_report._ops(NOW)))
    assert "Копии базы на ПК 8 дн." in text
    assert "Учения восстановления не прошли: копия не поднялась" in text
    assert "обновление ОС не прошло: dpkg прерван" in text

    ops_dir("drill", ts=NOW - 10 * DAY, ok=True, detail="ok")
    assert any("не было 10 дн." in a for a in _alerts(nightly_report._ops(NOW)))


class _NoDb:
    """Остальные разделы падают на ней и помечаются «не собрался» — нам нужен только ops."""
    def rollback(self):
        pass


def test_ops_are_collected_and_reach_the_alerts_of_the_whole_letter(ops_dir):
    #Обещание с вызывающим: раздел собирает сам collect, а не только тест.
    d = nightly_report.collect(_NoDb(), NOW)
    assert d["ops"]["bans"]["week"] == 16
    assert any("Копии базы вне сервера" in a for a in d["alerts"])
