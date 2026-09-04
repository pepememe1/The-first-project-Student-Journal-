"""
loadtest.py — Нагрузочный тест серверного API GradeBookAI.

Зачем: проверить, выдержит ли сервер одновременную работу всего колледжа
(>=1000 пользователей) и где у него потолок. Это НЕ юнит-тест (имя без шаблона
test_*.py / *_test.py — pytest его не собирает); запускается руками:

    cd server
    python tests/loadtest.py             # 1000 пользователей по умолчанию
    python tests/loadtest.py 1500 800    # 1500 пользователей, конкурентность 800

Что делает:
  1) Поднимает НАСТОЯЩИЙ uvicorn в подпроцессе на изолированной БД (временный файл
     SQLite; путь можно задать через GRADEBOOK_DB_URL) и ждёт /health.
  2) Заводит N пользователей (admin + преподаватели + студенты) и немного данных
     (занятия, оценки), чтобы pull возвращал реалистичный объём.
  3) Тремя фазами шлёт КОНКУРЕНТНЫЕ запросы через asyncio+httpx и замеряет:
       • Фаза A — N одновременных LOGIN (нагрузка на авторизацию; PBKDF2 — CPU);
       • Фаза B — N одновременных PULL (чтение; полный pull = поведение клиента v1);
       • Фаза C — конкурентный PUSH оценок преподавателями (запись; контеншн БД).
  4) Печатает сводку: успехи/ошибки, p50/p95/p99 задержек, throughput (req/s).

Честно по итогам: SQLite сериализует ЗАПИСЬ (один писатель) — под тысячами
одновременных это и есть узкое место. Лечится оно не сменой СУБД, а режимом WAL и
ожиданием блокировки (`db._sqlite_pragmas`) плюс мощностью машины: на компьютере
ВСГУТУ (Ryzen 9, 32 ГБ) запись упирается в диск, а не в блокировку. Масштабы колледжа
— тысячи строк и сотни одновременных, а не миллионы.
"""
import asyncio
import os
import socket
import subprocess
import sys
import time

#Консоль Windows бывает cp1251 — символы рамок/«→» в выводе роняли бы скрипт
#(UnicodeEncodeError). Делаем вывод неубиваемым, как и в main.py.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx

#Параметры (можно переопределить аргументами командной строки).
N_USERS = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
CONCURRENCY = int(sys.argv[2]) if len(sys.argv) > 2 else N_USERS
N_TEACHERS = max(1, N_USERS // 20)          #~5% преподавателей
N_LESSONS = 200                             #занятий-«семя» для реалистичного pull
PASSWORD = "loadtest-pass-1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(base: str, timeout: float = 30.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _pct(values, p):
    """p-й перцентиль в миллисекундах (values — секунды)."""
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[k] * 1000.0


def _summary(name, latencies, errors, wall):
    ok = len(latencies)
    total = ok + errors
    rps = total / wall if wall > 0 else 0
    print(f"\n── {name} ──")
    print(f"  запросов:     {total}  (успех {ok}, ошибок {errors})")
    print(f"  время фазы:   {wall:.2f} c   throughput: {rps:.0f} req/s")
    if latencies:
        print(f"  задержка ms:  p50 {_pct(latencies,50):.0f}   "
              f"p95 {_pct(latencies,95):.0f}   p99 {_pct(latencies,99):.0f}   "
              f"max {max(latencies)*1000:.0f}")
    return {"name": name, "ok": ok, "errors": errors, "rps": rps}


async def _seed(base):
    """Создаёт админа, N пользователей и немного данных. Возвращает (admin_headers,
    список логинов студентов, список логинов преподавателей)."""
    #Один хеш пароля на всех — чтобы не молотить PBKDF2 N раз при подготовке.
    sys.path.insert(0, os.path.abspath("."))
    from app.security import hash_password
    pwhash = hash_password(PASSWORD)

    async with httpx.AsyncClient(base_url=base, timeout=60) as c:
        r = await c.post("/auth/bootstrap-admin",
                         json={"login": "admin", "password": "adminpass1",
                               "full_name": "Админ"})
        r.raise_for_status()
        admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        teachers = [f"teacher{i}" for i in range(N_TEACHERS)]
        students = [f"student{i}" for i in range(N_USERS - N_TEACHERS)]
        users = []
        for t in teachers:
            users.append({"id": f"teach:{t}", "role": "teacher", "login": t,
                          "password_hash": pwhash, "full_name": t,
                          "subjects": ["Математика"]})
        for s in students:
            users.append({"id": f"stud:{s}", "role": "student", "login": s,
                          "password_hash": pwhash, "surname": s, "name": "Тест",
                          "group_name": "ИС-21"})
        lessons = [{"id": f"L{i}", "group_name": "ИС-21", "subject": "Математика",
                    "type": "Практика", "number": i, "topic": f"Тема {i}",
                    "date": "01.09.2025"} for i in range(N_LESSONS)]
        grades = [{"id": f"student{i}|Тест|L0", "student_f": f"student{i}",
                   "student_n": "Тест", "lesson_id": "L0", "grade": "5"}
                  for i in range(min(N_USERS, 1000))]

        print(f"Готовлю данные: {len(users)} пользователей, {len(lessons)} занятий, "
              f"{len(grades)} оценок ...")
        #Заливаем порциями, чтобы не упереться в размер одного запроса.
        for i in range(0, len(users), 500):
            r = await c.post("/sync/push",
                             json={"changes": {"users": users[i:i+500]}}, headers=admin_h)
            r.raise_for_status()
        r = await c.post("/sync/push",
                         json={"changes": {"lessons": lessons, "grades": grades}},
                         headers=admin_h)
        r.raise_for_status()
    return admin_h, students, teachers


async def _run_phase(name, base, tasks_fn, items):
    """Запускает по одной корутине на элемент items с ограничением CONCURRENCY,
    собирает задержки и ошибки."""
    latencies, errors = [], 0
    sem = asyncio.Semaphore(CONCURRENCY)
    limits = httpx.Limits(max_connections=CONCURRENCY,
                          max_keepalive_connections=min(CONCURRENCY, 200))
    async with httpx.AsyncClient(base_url=base, timeout=60, limits=limits) as c:
        async def one(item):
            nonlocal errors
            async with sem:
                t0 = time.perf_counter()
                try:
                    ok = await tasks_fn(c, item)
                    if ok:
                        latencies.append(time.perf_counter() - t0)
                    else:
                        errors += 1
                except Exception:
                    errors += 1
        t0 = time.perf_counter()
        await asyncio.gather(*(one(it) for it in items))
        wall = time.perf_counter() - t0
    return _summary(name, latencies, errors, wall)


async def _main():
    base_url_env = os.environ.get("GRADEBOOK_DB_URL", "")
    db_kind = "SQLite (%s)" % ("задана GRADEBOOK_DB_URL" if base_url_env else "temp")
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    #Изолированная БД и секрет — только если их не задали снаружи.
    env = dict(os.environ)
    if "GRADEBOOK_DB_URL" not in env:
        import tempfile
        dbpath = os.path.join(tempfile.gettempdir(), f"gradebook_load_{port}.db")
        if os.path.exists(dbpath):
            os.remove(dbpath)
        env["GRADEBOOK_DB_URL"] = "sqlite:///" + dbpath.replace("\\", "/")
    env.setdefault("GRADEBOOK_JWT_SECRET", "loadtest-secret")

    print(f"Запускаю сервер uvicorn на {base}  (БД: {db_kind}) ...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, cwd=os.path.abspath("."))
    try:
        if not _wait_health(base):
            print("СЕРВЕР НЕ ПОДНЯЛСЯ — прерываю."); return
        print("Сервер готов.\n")

        admin_h, students, teachers = await _seed(base)

        print(f"\n=== НАГРУЗКА: {N_USERS} пользователей, конкурентность {CONCURRENCY} ===")

        #Фаза A — конкурентный LOGIN (CPU: PBKDF2 на каждый вход). Токены сохраняем
        #прямо здесь — чтобы не логиниться повторно ещё раз (на больших N это вдвое
        #дольше). Дальше фазы B/C берут токены отсюда.
        tokens = {}
        async def do_login(c, login):
            r = await c.post("/auth/login", json={"login": login, "password": PASSWORD})
            if r.status_code == 200:
                tokens[login] = r.json()["access_token"]
                return True
            return False
        await _run_phase("Фаза A: LOGIN (вход всех пользователей)",
                         base, do_login, students + teachers)

        #Фаза B — конкурентный ПОЛНЫЙ pull (since="") = старое поведение клиента.
        async def do_pull(c, login):
            tok = tokens.get(login)
            if not tok:
                return False
            r = await c.get("/sync/pull",
                            headers={"Authorization": f"Bearer {tok}"})
            return r.status_code == 200
        #Полный pull при тысячах пользователей патологически тяжёл (таблица users
        #целиком в КАЖДОМ ответе) — это и есть причина перехода на дельту. Чтобы
        #прогон не шёл часами, замеряем старое поведение на ВЫБОРКЕ до 500 запросов;
        #login/дельта/push гоняем на всех пользователях.
        full_sample = (students + teachers)[:120]
        await _run_phase(f"Фаза B: ПОЛНЫЙ PULL (since='', старое поведение, выборка {len(full_sample)})",
                         base, do_pull, full_sample)

        #Фаза B2 — конкурентный ДЕЛЬТА-pull (since=server_time) = новое поведение.
        #Берём свежую метку; с этого момента изменений нет, поэтому дельта пуста и
        #запрос должен возвращаться почти мгновенно — это и есть выигрыш Фазы 2.
        async with httpx.AsyncClient(base_url=base, timeout=60) as c:
            wm = (await c.get("/sync/pull", headers={
                "Authorization": f"Bearer {next(iter(tokens.values()))}"})).json()["server_time"]

        async def do_pull_delta(c, login):
            tok = tokens.get(login)
            if not tok:
                return False
            r = await c.get("/sync/pull", params={"since": wm},
                            headers={"Authorization": f"Bearer {tok}"})
            return r.status_code == 200
        await _run_phase("Фаза B2: ДЕЛЬТА-PULL (since=метка, новое поведение)",
                         base, do_pull_delta, students + teachers)

        #Фаза C — конкурентный PUSH оценок преподавателями (запись; контеншн БД).
        #item = (login, n) — уникальный id на каждую попытку, чтобы измерять именно
        #пропускную способность записи, а не гонку одинаковых вставок.
        async def do_push(c, item):
            login, n = item
            tok = tokens.get(login)
            if not tok:
                return False
            gid = f"load|{login}|L{n}"
            r = await c.post("/sync/push", headers={"Authorization": f"Bearer {tok}"},
                             json={"changes": {"grades": [{
                                 "id": gid, "student_f": "load", "student_n": login,
                                 "lesson_id": "L0", "grade": "4"}]}})
            return r.status_code == 200
        #каждый преподаватель пушит несколько раз — усиливаем конкуренцию записи
        push_items = [(t, n) for t in teachers for n in range(10)]
        await _run_phase("Фаза C: PUSH (преподаватели пишут оценки)",
                         base, do_push, push_items)

        print("\n=== ИТОГ ===")
        print("Если в фазах B/C много ошибок или p99 в секундах — узкое место это "
              "ЗАПИСЬ в SQLite (один писатель) и мощность машины. Смотреть в таком "
              "порядке: включён ли WAL и busy_timeout (db._sqlite_pragmas), сколько "
              "у машины ядер и памяти (hostcaps.profile), не упирается ли диск. "
              "Несколько воркеров uvicorn НЕ вариант: реестр сокетов и ход "
              "активностей живут в памяти процесса.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(_main())
