"""
loadtest_login.py — Нагрузочный тест ТОЛЬКО входа (LOGIN) на 1000/2000/3000/5000
пользователей с реальным хешированием пароля (hybrid SHA512 + ГОСТ-Стрибог).

Зачем отдельно от loadtest.py: коммерческий вопрос «готова ли прога» упирается в вход
всего колледжа утром — а это CPU на PBKDF2/ГОСТ. Здесь замеряем именно это и печатаем
то, что просили: ОБЩЕЕ время на всех и время на ОДНОГО пользователя.

Запуск (не собирается pytest — имя не test_*):
    cd server
    python tests/loadtest_login.py                 # 1000,2000,3000,5000
    python tests/loadtest_login.py 500 1000         # свои N

Транспорт — локальный http (127.0.0.1). Через serveo.net поверх этого добавится
СЕТЕВАЯ задержка туннеля (примерно константа на запрос), но потолок CPU-хеша тот же:
на боевом сервере ВСГУТУ включается OpenSSL GOST-engine (C-скорость) вместо pure-Python.
"""
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import httpx

STEPS = [int(x) for x in sys.argv[1:]] or [1000, 2000, 3000, 5000]
PASSWORD = "loadtest-pass-1"
CONCURRENCY = 300          #одновременных входящих запросов (сервер всё равно упрётся в CPU)
#Барьер устройства: гоняем нагрузку «как хост» (device_id хоста пропускается сервером
#без подтверждения), поэтому шлём один и тот же X-Device-Id на всех запросах.
HOST_DEVICE_ID = "loadtest-host"
_DEV_HEADERS = {"X-Device-Id": HOST_DEVICE_ID}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(base: str, timeout: float = 40.0) -> bool:
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
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[k] * 1000.0


async def _seed(base, n_users):
    """Заводит админа и n_users пользователей с ОДНИМ общим хешем (готовим быстро)."""
    sys.path.insert(0, os.path.abspath("."))
    from app.security import hash_password
    pwhash = hash_password(PASSWORD)
    async with httpx.AsyncClient(base_url=base, timeout=120, headers=_DEV_HEADERS) as c:
        r = await c.post("/auth/bootstrap-admin",
                         json={"login": "admin", "password": "adminpass1",
                               "full_name": "Админ"})
        r.raise_for_status()
        admin_h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        logins = [f"user{i}" for i in range(n_users)]
        users = [{"id": f"u:{lg}", "role": "student", "login": lg,
                  "password_hash": pwhash, "surname": lg, "name": "Тест",
                  "group_name": "ИС-21"} for lg in logins]
        for i in range(0, len(users), 500):
            r = await c.post("/sync/push",
                             json={"changes": {"users": users[i:i+500]}}, headers=admin_h)
            r.raise_for_status()
    return logins


async def _login_phase(base, logins):
    """N конкурентных LOGIN. Возвращает (wall_sec, latencies, errors)."""
    latencies, errors = [], 0
    sem = asyncio.Semaphore(CONCURRENCY)
    limits = httpx.Limits(max_connections=CONCURRENCY,
                          max_keepalive_connections=min(CONCURRENCY, 200))
    async with httpx.AsyncClient(base_url=base, timeout=120, limits=limits, headers=_DEV_HEADERS) as c:
        async def one(lg):
            nonlocal errors
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await c.post("/auth/login",
                                     json={"login": lg, "password": PASSWORD})
                    if r.status_code == 200:
                        latencies.append(time.perf_counter() - t0)
                    else:
                        errors += 1
                except Exception:
                    errors += 1
        t0 = time.perf_counter()
        await asyncio.gather(*(one(lg) for lg in logins))
        wall = time.perf_counter() - t0
    return wall, latencies, errors


def _start_server():
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    dbpath = os.path.join(tempfile.gettempdir(), f"gb_loadlogin_{port}.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(dbpath + suffix)
        except OSError:
            pass
    env["GRADEBOOK_DB_URL"] = "sqlite:///" + dbpath.replace("\\", "/")
    env.setdefault("GRADEBOOK_JWT_SECRET", "loadtest-secret")
    env["GRADEBOOK_HOST_DEVICE_ID"] = HOST_DEVICE_ID
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env, cwd=os.path.abspath("."))
    return proc, base, dbpath


async def _run_one(n_users):
    proc, base, dbpath = _start_server()
    try:
        if not _wait_health(base):
            print(f"[N={n_users}] СЕРВЕР НЕ ПОДНЯЛСЯ"); return
        logins = await _seed(base, n_users)
        wall, lat, err = await _login_phase(base, logins)
        ok = len(lat)
        per_user_ms = (wall / n_users) * 1000.0        #общее / N = «на одного» (пропускная)
        avg_ms = (sum(lat) / ok * 1000.0) if ok else 0.0
        print(f"\n================  ВХОД: {n_users} пользователей  ================")
        print(f"  успешных входов: {ok} / {n_users}   ошибок: {err}")
        print(f"  ОБЩЕЕ время на всех:      {wall:.2f} c")
        print(f"  На ОДНОГО (общее / N):    {per_user_ms:.1f} мс")
        print(f"  Средняя задержка входа:   {avg_ms:.0f} мс "
              f"(p50 {_pct(lat,50):.0f} · p95 {_pct(lat,95):.0f} · p99 {_pct(lat,99):.0f})")
        print(f"  Пропускная способность:   {n_users / wall:.0f} вход/с")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


async def _main():
    print(f"Нагрузочный тест ВХОДА (SQLite, локальный http). Шаги: {STEPS}")
    print("Хеш пароля — hybrid SHA512+ГОСТ (как на бою; на dev ГОСТ pure-Python — медленнее C).\n")
    grand0 = time.perf_counter()
    for n in STEPS:
        await _run_one(n)
    print(f"\nВесь прогон занял {time.perf_counter() - grand0:.0f} c.")


if __name__ == "__main__":
    asyncio.run(_main())
