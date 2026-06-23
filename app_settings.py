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
import json
from urllib.parse import urlparse

import app_paths

#Боевая сборка: сюда впишем адрес сервера ВСГУТУ. Для боевой работы — https://
#(ПДн по сети только в шифрованном канале, 152-ФЗ). Пример: "https://journal.vsgutu.ru".
DEFAULT_API_URL = ""

API_CONFIG_FILE = "api_config.json"


def is_secure_transport(url: str) -> bool:
    """Безопасен ли канал к серверу.

    Безопасным считаем https (шифрование в пути) и http к локальной петле
    (127.0.0.1/localhost — трафик не покидает машину, это dev-режим). http к
    УДАЛЁННОМУ хосту небезопасен: логины, пароли и оценки пойдут по сети открытым
    текстом. Пустой адрес = офлайн без сервера, течь нечему — тоже «безопасно».

    Нужно, чтобы предупредить администратора до того, как ПДн уедут незашифрованными
    (см. SyncClient), а не постфактум."""
    url = (url or "").strip()
    if not url:
        return True
    p = urlparse(url)
    if p.scheme == "https":
        return True
    host = (p.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def get_api_url() -> str:
    """Адрес сервера синхронизации или '' (тогда — офлайн без сервера)."""
    try:
        p = app_paths.app_file(API_CONFIG_FILE)
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


def dev_tunnel_enabled() -> bool:
    """Показывать ли в админке кнопку «Доступ из интернета» (ssh-туннель serveo).

    По умолчанию ВЫКЛЮЧЕНО — это боевой профиль: serveo гонит ПДн через чужой
    иностранный сервис, для реальных данных студентов так нельзя (152-ФЗ). Туннель
    остаётся только как dev/demo-инструмент «быстро показать коллеге на выдуманных
    данных» и включается явно: переменная окружения GRADEBOOK_ENABLE_TUNNEL=1.
    Боевой доступ — домен + Caddy/HTTPS в РФ (см. server/DEPLOY.md, раздел 7.6)."""
    val = os.environ.get("GRADEBOOK_ENABLE_TUNNEL", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def set_api_url(url: str) -> bool:
    """Сохраняет адрес сервера в api_config.json рядом с программой."""
    try:
        p = app_paths.app_file(API_CONFIG_FILE)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"api_url": (url or "").strip()}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[app_settings] не удалось сохранить api_url: {e}")
        return False


def write_api_config(path: str, url: str) -> bool:
    """Пишет api_config.json с заданным адресом по ПРОИЗВОЛЬНОМУ пути.

    Это для раздачи: админ сохраняет файл с публичным адресом своего сервера и
    отдаёт коллегам — они кладут его рядом со своей программой, и она знает, куда
    подключаться. От set_api_url отличается тем, что пишет не «себе» (рядом с этой
    программой), а в указанное место."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"api_url": (url or "").strip()}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[app_settings] не удалось записать api_config: {e}")
        return False
