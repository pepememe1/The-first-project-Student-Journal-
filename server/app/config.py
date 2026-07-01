"""
config.py — Настройки бэкенда из переменных окружения.

Читаем напрямую из os.environ (без лишних зависимостей). Для разработки есть
безопасные дефолты (SQLite, dev-секрет). На боевом сервере значения задаются
через server/.env или системные переменные окружения.
"""
import os


def _load_dotenv():
    """Минимальный загрузчик server/.env (KEY=VALUE), без сторонних пакетов."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
    except Exception as e:
        print(f"[config] не удалось прочитать .env: {e}")


_load_dotenv()

#Разработка — SQLite рядом с проектом; боевой сервер — PostgreSQL (см. .env).
DATABASE_URL = os.environ.get("GRADEBOOK_DB_URL", "sqlite:///./gradebook_server.db")

#Секрет подписи JWT. На бою ОБЯЗАТЕЛЬНО переопределить длинной случайной строкой.
JWT_SECRET = os.environ.get("GRADEBOOK_JWT_SECRET", "dev-secret-change-me")
JWT_ALG = "HS256"
#Access-токен сгорает через 5 часов. ВАЖНО: exp — АБСОЛЮТНАЯ метка времени, выставленная
#сервером при выдаче, и проверяется сервером на каждом запросе. Поэтому офлайн-время тоже
#идёт: вернулся в сеть позже срока — токен уже мёртв (обойти, выключив сеть, нельзя).
#Дальше работу продлевает refresh-токен (тихое обновление), а не «заморозка» времени.
JWT_TTL_MIN = int(os.environ.get("GRADEBOOK_JWT_TTL_MIN", "300"))  # 5 часов (access)
#Refresh-токен живёт долго: им тихо обновляют короткий access, не выкидывая
#пользователя на логин (например, когда токен протух за время офлайна). Отзывается
#через чёрный список (AuthSession.revoked), поэтому длинный срок безопасен.
JWT_REFRESH_TTL_MIN = int(os.environ.get("GRADEBOOK_JWT_REFRESH_TTL_MIN", str(30 * 24 * 60)))  # 30 дней

#CORS: какие сайты-источники могут обращаться к API из браузера.
#Десктопу CORS не нужен (это не браузер). Для будущего сайта укажите его домен,
#напр. GRADEBOOK_ALLOWED_ORIGINS="https://journal.vsgutu.ru". По умолчанию "*"
#(удобно для разработки; для прод-сайта лучше сузить до конкретного домена).
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("GRADEBOOK_ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]
