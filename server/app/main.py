"""
main.py — Точка входа бэкенда GradeBookAI (FastAPI).

Запуск (разработка):
    cd server
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Документация API после запуска: http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .config import ALLOWED_ORIGINS
from .routers import auth, sync, me, admin, web
from .routers import connect as connect_router
from . import events, throttle


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # создаём таблицы при старте
    events.record("info", "server_start", "сервер запущен")
    yield


app = FastAPI(title="GradeBookAI API", version="0.1.0", lifespan=lifespan)

#CORS: список разрешённых источников берётся из настроек (GRADEBOOK_ALLOWED_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):
    """Любая НЕперехваченная ошибка попадает в админскую консоль и отдаётся клиенту
    как аккуратный 500 (без утечки стек-трейса наружу). Свои HTTPException (401/403/
    409/429 и т.п.) сюда не попадают — у них собственный обработчик FastAPI."""
    try:
        events.record("error", "server_error", f"{type(exc).__name__}: {exc}",
                      ip=throttle.client_ip(request))
    except Exception:
        pass
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})


import os
from fastapi.responses import FileResponse


def _find_web_dist() -> str:
    """Папка собранного САЙТА (dist), которую сервер отдаёт с ТОГО ЖЕ адреса, что и API.
    Ищем: переменная окружения → bundled server/webdist → рядом лежащий репозиторий
    веб-версии (dev-раскладка). Нет папки — сервер работает как чистый API (визитка на «/»)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../server
    root_dir = os.path.dirname(here)                                    # корень десктоп-репо
    parent = os.path.dirname(root_dir)                                  # уровень выше (напр. GB_2_7)
    candidates = [
        os.environ.get("GRADEBOOK_WEB_DIST", "").strip(),
        os.path.join(here, "webdist"),
        os.path.join(parent, "GradeBookAI-Web-Edition", "dist"),
        os.path.join(root_dir, "GradeBookAI-Web-Edition", "dist"),
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "index.html")):
            return os.path.realpath(c)
    return ""


WEB_DIST = _find_web_dist()


@app.get("/", tags=["service"], include_in_schema=False)
def root():
    #Есть собранный сайт → отдаём его (адрес сервера = адрес сайта). Нет — короткая
    #«визитка» API, чтобы при заходе в браузере было видно «сервер жив».
    if WEB_DIST:
        return FileResponse(os.path.join(WEB_DIST, "index.html"))
    return JSONResponse({"service": "GradeBookAI API", "status": "ok", "docs": "/docs"})


@app.get("/health", tags=["service"])
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(connect_router.router)
app.include_router(web.router)


#САЙТ (SPA): отдаём собранный фронтенд с ТОГО ЖЕ адреса, что и API. Монтируем ПОСЛЕ
#всех API-роутеров, поэтому /auth, /web, /docs и т.п. имеют приоритет. Неизвестные
#НЕ-API пути возвращают index.html (клиентский роутинг Vue), существующие файлы
#(assets/, mascot/, favicon) — как есть. Нет dist — блок не подключается.
if WEB_DIST:
    from fastapi.staticfiles import StaticFiles

    _assets_dir = os.path.join(WEB_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        target = os.path.realpath(os.path.join(WEB_DIST, full_path))
        #защита от path traversal: отдаём только файлы ВНУТРИ dist
        if target.startswith(WEB_DIST) and os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(os.path.join(WEB_DIST, "index.html"))
