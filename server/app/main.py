"""
main.py — Точка входа бэкенда GradeBookAI (FastAPI).

Запуск (разработка):
    cd server
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Документация API после запуска: http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .config import ALLOWED_ORIGINS
from .routers import auth, sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()   # создаём таблицы при старте
    yield


app = FastAPI(title="GradeBookAI API", version="0.1.0", lifespan=lifespan)

#CORS: список разрешённых источников берётся из настроек (GRADEBOOK_ALLOWED_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["service"])
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(sync.router)
