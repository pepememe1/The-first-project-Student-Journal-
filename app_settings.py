"""
app_settings.py — Локальные настройки ПК (НЕ синхронизируются).

Главное здесь — адрес сервера синхронизации (API). Его нельзя тянуть из самой
синхронизации (новый ПК не узнал бы, куда подключаться), поэтому он задаётся
локально одним из способов (по приоритету):
  1. файл api_config.json рядом с программой: {"api_url": "http://СЕРВЕР:8000"};
  2. переменная окружения GRADEBOOK_API_URL (удобно для разработки);
  3. зашитый в сборку DEFAULT_API_URL (для боевой поставки — заполнить).

Пустой адрес = офлайн-режим без сервера: прога работает только локально (это
штатный режим, не ошибка).
"""
import os
import sys
import json

# ⚙️ Боевая сборка: впишите адрес сервера ВСГУТУ, напр. "http://10.0.0.5:8000".
DEFAULT_API_URL = ""

API_CONFIG_FILE = "api_config.json"


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_api_url() -> str:
    """Адрес сервера синхронизации или '' (тогда — офлайн без сервера)."""
    try:
        p = os.path.join(_app_dir(), API_CONFIG_FILE)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                url = (json.load(f) or {}).get("api_url", "")
            if url:
                return url.strip()
    except Exception:
        pass
    env = os.environ.get("GRADEBOOK_API_URL", "").strip()
    if env:
        return env
    return DEFAULT_API_URL.strip()


def set_api_url(url: str) -> bool:
    """Сохраняет адрес сервера в api_config.json рядом с программой."""
    try:
        p = os.path.join(_app_dir(), API_CONFIG_FILE)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"api_url": (url or "").strip()}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[app_settings] не удалось сохранить api_url: {e}")
        return False
