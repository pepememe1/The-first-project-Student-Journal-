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
#По требованию — ЖЁСТКАЯ сессия ~5 часов: refresh = access, после 5 часов всё
#истекает и нужен повторный вход. Раньше refresh жил 30 дней (тихое продление) — из-за
#этого в мониторинге/сессиях «копилось» до ~700 часов. Теперь этого нет. Переопределить
#можно переменной GRADEBOOK_JWT_REFRESH_TTL_MIN (напр. вернуть 43200 = 30 дней).
JWT_REFRESH_TTL_MIN = int(os.environ.get("GRADEBOOK_JWT_REFRESH_TTL_MIN", str(JWT_TTL_MIN)))  # = access (5 ч)

#CORS: какие сайты-источники могут обращаться к API из браузера.
#Десктопу CORS не нужен (это не браузер). Для будущего сайта укажите его домен,
#напр. GRADEBOOK_ALLOWED_ORIGINS="https://journal.vsgutu.ru". По умолчанию "*"
#(удобно для разработки; для прод-сайта лучше сузить до конкретного домена).
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("GRADEBOOK_ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]


#WebAuthn (passkeys — вход по Face ID/отпечатку без пароля).
#  • WEBAUTHN_ORIGIN — полный https-origin сайта (напр. https://esstu-gradebook.ru),
#    с которым должна совпасть подпись ключа;
#  • WEBAUTHN_RP_ID — «имя» доверенной стороны = ДОМЕН без схемы/порта (esstu-gradebook.ru);
#    passkey привязывается к нему, поэтому менять его нельзя, иначе ключи «отвалятся».
#По умолчанию берём первый https из ALLOWED_ORIGINS, иначе localhost для разработки.
def _default_origin() -> str:
    for o in ALLOWED_ORIGINS:
        if o.startswith("https://"):
            return o.rstrip("/")
    return "http://localhost:5173"


def _host_of(origin: str) -> str:
    from urllib.parse import urlparse
    return urlparse(origin).hostname or "localhost"


WEBAUTHN_ORIGIN = (os.environ.get("GRADEBOOK_WEBAUTHN_ORIGIN", "").strip() or _default_origin())
WEBAUTHN_RP_ID = (os.environ.get("GRADEBOOK_WEBAUTHN_RP_ID", "").strip() or _host_of(WEBAUTHN_ORIGIN))
WEBAUTHN_RP_NAME = os.environ.get("GRADEBOOK_WEBAUTHN_RP_NAME", "GradeBookAI — ВСГУТУ")
