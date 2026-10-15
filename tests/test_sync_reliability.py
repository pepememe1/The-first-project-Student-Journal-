"""test_sync_reliability.py — безотказность синхронизации: три найденных дефекта и
два инварианта, на которых держится дельта.

Почему отдельным файлом, а не в test_delta_push.py: там проверяется, ЧТО уезжает
(состав дельты), здесь — что происходит, когда что-то идёт НЕ ТАК. Это разные вопросы,
и смешивать их значит потерять оба при первом же падении.

Каждый тест ниже закрывает поведение, которого раньше не было ВООБЩЕ, — то есть до
починки он краснел. Это проверено вручную откатом правки, а не предположено.
"""
import threading
import time

import pytest



class _FakeClient:
    """Клиент, которым можно управлять: что вернуть на push и сколько он длится."""

    def __init__(self, push_result=None, push_delay=0.0):
        self.push_result = push_result if push_result is not None else {}
        self.push_delay = push_delay
        self.pushes = 0
        self.pulls = 0

    def push(self, changes):
        self.pushes += 1
        if self.push_delay:
            time.sleep(self.push_delay)
        return dict(self.push_result)

    def pull(self, since=""):
        self.pulls += 1
        return {"server_time": "2026-08-13T12:00:00+00:00", "changes": {}}


# ── 1. Отвергнутые сервером правки больше не исчезают молча ────────────────────────
# ── 2. Два цикла одновременно не пересекаются ──────────────────────────────────────
# ── 3. Водяной знак не уезжает вперёд при неудачном push ───────────────────────────
# ── 3.1 Часы ушли назад — дельте верить нельзя ─────────────────────────────────────
# ── 3.2 Порционный push: большой снимок уезжает пачками ────────────────────────────
# ── 4. Инвариант формата метки времени ─────────────────────────────────────────────
# ── 5. Сверка «сервер = истина» ОБЯЗАНА иметь вызывающего ──────────────────────────
def test_reconcile_has_a_caller_in_the_product():
    """Инвариант §4.5 живёт только пока сверку «сервер = истина» кто-то ЗОВЁТ.

    🔥 Он уже однажды не жил. Единственный вызывающий (`main_window._restore_client_bg`)
    исчез вместе с `main_window.py` при удалении Qt-оболочки: функция осталась, тесты на
    неё остались зелёными, а выполняться перестала совсем.

    ⚠️ С 25.09.2026 (аудит F-02/F-03) сверяется КОПИЯ ИНТЕРФЕЙСА — `local_mirror.rebuild`,
    а не старая база (`sync_engine.reconcile`): её интерфейс не читает, и убирать «сирот»
    там значило убирать их не там, где их видит человек. Тест по-прежнему проверяет ФАКТ
    вызова из рабочего цикла, а не поведение сверки (оно покрыто в test_desk_outbox.py).
    """
    import inspect
    from sync import sync_runner
    mirror = inspect.getsource(sync_runner.SyncManager._mirror_for_vue)
    assert "local_mirror.rebuild(" in mirror, (
        "цикл не зовёт сверку копии — «сервер = истина» снова осиротела")
    #И она должна стоять на пути ЦИКЛА, а не в мёртвой ветке.
    assert "self._mirror_for_vue()" in inspect.getsource(sync_runner.SyncManager._loop)


def test_reconcile_runs_once_per_session(monkeypatch):
    """Полная сверка копии идёт РОВНО один раз за сессию входа, дальше — дельта.

    Повтор каждые 30 c означал бы полный снимок в каждом цикле — самый дорогой обмен из
    всех. ⚠️ Освобождения «хоста» больше нет: сверяется копия интерфейса, производные
    данные, и авторитетную копию она не трогает ни на какой машине."""
    import desktop.local_mirror as lm
    from sync import sync_runner

    calls = []
    monkeypatch.setattr(lm, "rebuild", lambda client=None: calls.append("full") or {"ok": True})
    monkeypatch.setattr(lm, "mirror_once", lambda client=None: calls.append("delta") or {"ok": True})
    monkeypatch.setattr(sync_runner.SyncManager, "_rebuild_requested", staticmethod(lambda: False))

    r = sync_runner.SyncManager()
    r._need_reconcile = True
    r._mirror_for_vue()
    r._mirror_for_vue()
    assert calls == ["full", "delta"], f"сверка не один раз за сессию: {calls}"
    assert r._need_reconcile is False


def test_failed_reconcile_is_retried_next_cycle(monkeypatch):
    """Сверка не удалась — флаг НЕ снимаем: иначе один блип сети отменял бы её до
    следующего входа, а именно ради накопившихся расхождений она и нужна."""
    import desktop.local_mirror as lm
    from sync import sync_runner

    monkeypatch.setattr(lm, "rebuild", lambda client=None: {"ok": False, "error": "сеть"})
    monkeypatch.setattr(sync_runner.SyncManager, "_rebuild_requested", staticmethod(lambda: False))
    monkeypatch.setattr(sync_runner.SyncManager, "_request_rebuild", staticmethod(lambda: None))

    r = sync_runner.SyncManager()
    r._need_reconcile = True
    r._mirror_for_vue()
    assert r._need_reconcile is True, "провал сверки должен оставлять её в очереди"
    assert r._mirror_error == "сеть", "провал сверки обязан быть виден в состоянии синка"


# ── 9. Конфликт оценки перестал быть беззвучным ───────────────────────────────────
def test_conflict_counter_reaches_the_sync_status():
    """Счётчик конфликтов обязан доезжать до состояния, которое видит интерфейс.

    ⚠️ С 25.09.2026 конфликты живут в очереди правок (`desk_outbox`), а не в старой базе:
    её слияние считало «конфликтом» любую свежую серверную оценку, и значок показывал
    расхождения, разрешить которые было негде. Проводка «очередь → /desk/sync/status →
    значок» держится в `tests/test_local_api.py::test_sync_status_reports_the_outbox`;
    здесь — что старые счётчики из статуса УБРАНЫ и не вводят человека в заблуждение."""
    from sync import sync_runner
    st = sync_runner.SyncManager().status()
    assert "conflicts" not in st and "rejected" not in st, (
        "счётчики старой базы вернулись в статус — они показывали бы вечные «конфликты»")
    assert "mirror_error" in st and "mirror_ok_at" in st


def test_sync_status_has_a_real_consumer():
    """СТРУКТУРНЫЙ сторож: у `status()` обязан быть вызывающий В ПРОДУКТЕ, а не в тестах.

    Зачем такой странный тест. Обычная проверка «status() возвращает conflicts» была
    зелёной ровно в тот период, когда значение не читал НИКТО: индикатор удалили вместе с
    Qt, и починка «конфликт теперь звучит» превратилась в обещание без вызывающего. Это
    самый частый класс дефекта в этом проекте (`:min-zet`, `saveEndpoint`, эндпоинт
    профиля без единого вызова), и ловится он только так — проверкой, что у обещания есть
    потребитель. Заглушить его, дописав вызов в тест, нельзя: тесты из поиска исключены.

    🔥 Ищем НАСТОЯЩИЙ вызов, а не упоминание. Первая версия этого сторожа искала
    подстроку и была зелёной БЕЗ правки: `sync_runner.status()` встречается в
    комментариях `data/core.py` и `sync_engine.py`, а `/desk/sync/status` — в шапке
    самого значка. То есть сторож подтверждал наличие потребителя по тексту, который
    ничего не вызывает. Проверено обратным ходом, поэтому здесь разбор синтаксиса.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    callers = []

    #Python: настоящий вызов вида `sync_runner.status()` — узел Call, а не текст.
    for rel in ("main.py", "desktop", "data", "sync", "server/app"):
        p = root / rel
        files = [p] if p.is_file() else [f for f in p.rglob("*.py")
                                         if "__pycache__" not in f.parts]
        for f in files:
            if f.name == "sync_runner.py":      #определение обёртки — не её вызов
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "status"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "sync_runner"):
                    callers.append(f"{f.relative_to(root)}:{node.lineno}")

    #Фронт: обращение к маршруту в КОДЕ, а не в комментарии. Строки-комментарии
    #отбрасываем целиком — этого достаточно, внутри строкового литерала «//» у нас нет.
    for f in (root / "web" / "src").rglob("*"):
        if f.suffix not in (".js", ".vue"):
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            bare = line.strip()
            if bare.startswith(("//", "*", "/*")):
                continue
            if "/desk/sync/status" in bare:
                callers.append(f"{f.relative_to(root)}:{i}")

    assert callers, ("у sync_runner.status() нет ни одного НАСТОЯЩЕГО потребителя в "
                     "продукте — значит конфликты и отвергнутые сервером правки снова "
                     "видны только строкой в логе, которую никто не читает")


