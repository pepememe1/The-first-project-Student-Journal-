"""
run.py — Удобный запуск бэкенда одной командой.

Зачем: main.py использует относительные импорты (from .db import ...), поэтому
его НЕЛЬЗЯ запускать как обычный скрипт (python app/main.py) — будет ошибка
"attempted relative import with no known parent package". Запускать надо как
модуль пакета. Этот файл делает это за вас.

Запуск ИЗ папки server:
    cd server
    python run.py
Эквивалентно: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("GRADEBOOK_PORT", "8000"))
    #host 0.0.0.0 — чтобы сервер был виден другим машинам в сети, а не только
    #localhost. reload=True удобно при разработке (перезапуск на правки кода).
    uvicorn.run("app.main:app", host="0.0.0.0", port=port,
                reload=bool(os.environ.get("GRADEBOOK_RELOAD")))
