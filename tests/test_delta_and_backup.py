"""
test_delta_and_backup.py — Дельта-синхронизация (метка last_sync, отсутствие
self-wake) и авто-бэкап по расписанию.
"""
from data.core import DBManager
from data.data_store import get_sync_watermark, get_store


class _FakeClient:
    """Заглушка клиента: запоминает since у pull, отдаёт растущий server_time."""
    def __init__(self):
        self.pull_sinces = []
        self.t = 0

    def push(self, changes):
        return {"applied": {}}

    def pull(self, since=""):
        self.pull_sinces.append(since)
        self.t += 1
        return {"server_time": f"T{self.t}", "changes": {}}


def test_backup_if_due_throttles(fresh_db):
    """backup_if_due делает копию не чаще интервала (троттлинг по времени)."""
    p1 = DBManager.backup_if_due(min_interval_sec=1800)
    assert p1
    assert DBManager.backup_if_due(min_interval_sec=1800) == ""   #ещё рано
    p3 = DBManager.backup_if_due(min_interval_sec=0)              #интервал истёк
    assert p3 and p3 != p1
    assert len(DBManager.list_backups()) == 2


def test_backup_if_due_survives_future_mtime(fresh_db, monkeypatch):
    """Метка последнего бэкапа «в будущем» НЕ должна отменять новую копию.

    Так бывает штатно: NTFS хранит время с точностью 100 нс, а time.time() читает
    системный таймер с шагом ~15 мс, и свежесозданный файл регулярно выглядит новее
    текущего момента. Тот же эффект даёт перевод часов назад по NTP. Наивная проверка
    `elapsed < interval` в этом случае молча переставала делать бэкапы — именно она и
    роняла соседний тест раз в несколько полных прогонов.
    """
    p1 = DBManager.backup_if_due(min_interval_sec=0)
    assert p1

    real_list = DBManager.list_backups

    def list_with_future_mtime():
        rows = real_list()
        #Сдвигаем метку самого свежего бэкапа на минуту ВПЕРЁД от текущего момента.
        return [(n, p, s, m + 60) for (n, p, s, m) in rows]

    monkeypatch.setattr(DBManager, "list_backups", staticmethod(list_with_future_mtime))
    p2 = DBManager.backup_if_due(min_interval_sec=0)
    assert p2 and p2 != p1, "бэкап пропущен из-за метки в будущем"

    #А вот честно свежий бэкап при непустом интервале по-прежнему тормозит новый.
    monkeypatch.setattr(DBManager, "list_backups", staticmethod(real_list))
    assert DBManager.backup_if_due(min_interval_sec=1800) == ""
