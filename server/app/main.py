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
from .routers import auth, sync, admin
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


@app.get("/health", tags=["service"])
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(admin.router)
