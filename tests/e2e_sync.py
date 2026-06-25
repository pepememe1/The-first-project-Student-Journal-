"""
e2e_sync.py — Сквозной тест синхронизации «два устройства через живой сервер».

Это НЕ юнит-тест (поднимает реальный uvicorn в подпроцессе); запуск руками:
    python tests/e2e_sync.py

Что проверяет (главное про «данные сохраняются и не путаются»):
  1) Устройство A заводит группу, студентов, занятия, оценки → push на сервер.
  2) Устройство B (ЧИСТАЯ локальная база) → pull → данные A появляются у B
     В ТОЧНОСТИ и без перепутывания (у каждого студента своя оценка за своё занятие).
  3) Устройство A удаляет занятие и студента → push; устройство B → pull →
     удаление доезжает (надгробия), удалённое не «воскресает».

Два «устройства» в одном процессе моделируем сбросом локальной базы между фазами
(LOCAL_DB фиксируется при импорте, поэтому отдельную папку данных задаём заранее).
Сервер — отдельный процесс, общение строго по HTTP (как у настоящего клиента).
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import glob

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#Папка данных клиента — до импорта клиентских модулей.
_DATA = tempfile.mkdtemp(prefix="gbai_e2e_")
os.environ["LOCALAPPDATA"] = _DATA
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

import requests  # noqa: E402
from core import DBManager, GradeBook, LOCAL_DB  # noqa: E402
import sync_engine  # noqa: E402
import data_store  # noqa: E402
from sync_client import SyncClient  # noqa: E402

G, S = "ИС-21", "Математика"
_ok = True


def check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), name)
    _ok = _ok and cond


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wipe_device():
    """Имитируем НОВОЕ устройство: чистая локальная база и сброс кэшей/сессии."""
    for f in glob.glob(LOCAL_DB + "*"):
        try:
            os.remove(f)
        except OSError:
            pass
    DBManager.init()
    data_store._STORE = None if hasattr(data_store, "_STORE") else None
    sync_engine._session_full_pull_done = False


def main():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    srv_db = os.path.join(tempfile.gettempdir(), f"e2e_server_{port}.db")
    for f in glob.glob(srv_db + "*"):
        try:
            os.remove(f)
        except OSError:
            pass
    env["GRADEBOOK_DB_URL"] = "sqlite:///" + srv_db.replace("\\", "/")
    env["GRADEBOOK_JWT_SECRET"] = "e2e-secret"

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning"],
        env=env, cwd=os.path.join(_REPO, "server"))
    try:
        for _ in range(60):
            try:
                if requests.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.3)
        else:
            print("СЕРВЕР НЕ ПОДНЯЛСЯ"); return 1

        client = SyncClient(base)
        client.bootstrap_admin("admin", "adminpass1")   #первый админ + токен

        # ── Устройство A: заводим данные и пушим ──
        _wipe_device()
        store = data_store.get_store()
        store.set_groups([{"name": G, "subjects": [S]}])
        store.set_students([
            {"surname": "Иванов", "name": "Иван", "group": G, "login": "ivanov"},
            {"surname": "Петров", "name": "Пётр", "group": G, "login": "petrov"},
        ])
        gb = GradeBook(G, S)
        l1 = gb.add_lesson("Практика", "Тема1", "01.09.2025")
        l2 = gb.add_lesson("Практика", "Тема2", "02.09.2025")
        for st in gb.spisok_stud:
            #у каждого студента РАЗНЫЕ оценки — чтобы поймать перепутывание
            st.records[l1.id] = "5" if st.f == "Иванов" else "3"
            st.records[l2.id] = "4" if st.f == "Иванов" else "2"
        gb.save_to_db()
        sync_engine.sync_once(client)   #push A → сервер

        # ── Устройство B: чистая база, тянем с сервера ──
        _wipe_device()
        sync_engine.sync_once(client)   #pull сервер → B
        b_store = data_store.get_store()
        b_students = sorted(s["surname"] for s in b_store.get_students())
        check("B получил обоих студентов A", b_students == ["Иванов", "Петров"])

        gbB = GradeBook(G, S)
        check("B получил оба занятия A", len(gbB.lessons) == 2)
        by_surname = {s.f: s for s in gbB.spisok_stud}
        #КЛЮЧЕВОЕ: оценки не перепутаны между студентами/занятиями
        iv_ok = (by_surname["Иванов"].records.get(l1.id) == "5" and
                 by_surname["Иванов"].records.get(l2.id) == "4")
        pe_ok = (by_surname["Петров"].records.get(l1.id) == "3" and
                 by_surname["Петров"].records.get(l2.id) == "2")
        check("оценки привязаны к ПРАВИЛЬНЫМ студентам/занятиям (не перепутаны)", iv_ok and pe_ok)

        # ── Удаление на A распространяется на B ──
        _wipe_device()
        sync_engine.sync_once(client)        #A снова актуально (pull всё)
        gbA = GradeBook(G, S)
        del_lesson = gbA.lessons[0].id
        gbA.delete_lesson(del_lesson)         #удалили занятие
        gbA.delete_student("Петров", "Пётр")  #удалили студента
        # удаление студента — через data_store (надгробие), как в админке
        store = data_store.get_store()
        store.set_students([{"surname": "Иванов", "name": "Иван", "group": G, "login": "ivanov"}])
        sync_engine.sync_once(client)         #push удаления

        _wipe_device()
        sync_engine.sync_once(client)         #B тянет удаления
        gbB2 = GradeBook(G, S)
        check("удалённое занятие не воскресло у B", del_lesson not in [l.id for l in gbB2.lessons])
        surnames_b = [s.f for s in gbB2.spisok_stud]
        check("удалённый студент не воскрес у B", "Петров" not in surnames_b)
        check("оставшийся студент жив у B", "Иванов" in surnames_b)

        print("\n=== E2E ИТОГ: " + ("ВСЁ СОШЛОСЬ ✓" if _ok else "ЕСТЬ РАСХОЖДЕНИЯ ✗") + " ===")
        return 0 if _ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
