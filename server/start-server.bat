@echo off
rem ============================================================
rem start-server.bat — запуск СЕРВЕРА (API, Python/FastAPI).
rem Просто дважды кликни. Откроется окно, сервер поднимется на порту 8000.
rem Проверка: http://localhost:8000/health -> {"status":"ok"}
rem ============================================================
cd /d "%~dp0"
echo Запускаю сервер API на http://localhost:8000
echo Документация всех эндпоинтов: http://localhost:8000/docs
echo Чтобы остановить — закрой это окно или нажми Ctrl+C.
python -m uvicorn app.main:app --reload --port 8000
pause
