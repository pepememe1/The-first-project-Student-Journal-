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
        with open(path, encoding="utf-8") as f:
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

#Шифрование ФАЙЛА БД при хранении (SQLCipher, AES-256) — ПДн at rest (152-ФЗ). Ключ —
#64 hex (32 байта), хранится в server/.env (chmod 600), НЕ в git. Задан + драйвер
#sqlcipher3 установлен → файл БД шифруется целиком, приложение работает как обычно
#(схема id не меняется). Пусто/нет драйвера → обычный SQLite (dev/Windows). См. db.py.
DB_KEY = os.environ.get("GRADEBOOK_DB_KEY", "").strip()

#Секрет подписи JWT. На бою ОБЯЗАТЕЛЬНО переопределить длинной случайной строкой.
DEV_JWT_SECRET = "dev-secret-change-me"
JWT_SECRET = os.environ.get("GRADEBOOK_JWT_SECRET", DEV_JWT_SECRET)
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

#⚠️ ОТДЕЛЬНЫЙ, БОЛЕЕ ДЛИННЫЙ потолок для МОБИЛЬНОГО приложения — 7 суток.
#Решение осознанное и НЕ распространяется на сайт и десктоп. Причина в том, чем эти
#устройства отличаются физически: телефон личный, лежит в кармане и заперт блокировкой
#экрана самого устройства; компьютер в аудитории колледжа общий, и человек уходит от
#него, не выйдя из аккаунта, — там пятичасовой потолок и есть основная защита.
#Требовать вход в приложение каждые пять часов означало, что студент открывает журнал
#на перемене и вместо оценок видит форму входа: люди перестают пользоваться, а не
#становятся защищённее.
#Какому клиенту какой потолок — решает НЕ заголовок запроса, а поле auth_sessions.client,
#записанное ОДИН РАЗ при входе (см. models.AuthSession). Иначе браузер, приславший
#X-Client: android, растянул бы обычную веб-сессию до недели.
JWT_MOBILE_TTL_MIN = int(os.environ.get("GRADEBOOK_JWT_MOBILE_TTL_MIN", "10080"))  # 7 суток

#Мобильная сессия кончается не «через неделю», а В БЛИЖАЙШИЙ ПОНЕДЕЛЬНИК 00:00 по
#местному времени: у всего колледжа один и тот же понятный рубеж («в понедельник
#вход заново»), а не у каждого свой в зависимости от того, когда он однажды вошёл.
#Понедельник МЕСТНЫЙ, а не UTC: Улан-Удэ — UTC+8, и по UTC граница пришлась бы на
#воскресенье 16:00 по-местному, то есть на сутки раньше обещанного.
COLLEGE_UTC_OFFSET_H = int(os.environ.get("GRADEBOOK_TZ_OFFSET_H", "8"))

#Нижняя граница той же сессии. Без неё вход в воскресенье вечером давал бы сессию на
#пару часов — формально «до понедельника», а на деле бесполезную: человек открыл бы
#приложение утром и увидел форму входа. Сутки — минимум, ради которого всё и делалось.
JWT_MOBILE_FLOOR_MIN = int(os.environ.get("GRADEBOOK_JWT_MOBILE_FLOOR_MIN", "1440"))  # 24 ч

#⚠️ Сколько приложение вправе работать БЕЗ СВЯЗИ. Проверить это на сервере невозможно
#по определению (сервера в этот момент нет), поэтому окно закрывает сам клиент, считая
#от последнего успешного ответа. Значение живёт здесь, чтобы у сервера и приложения
#была одна цифра, и отдаётся клиенту в /me/prefs — иначе договорённость разъехалась бы
#молча при первой же правке одной из сторон.
OFFLINE_GRACE_MIN = int(os.environ.get("GRADEBOOK_OFFLINE_GRACE_MIN", "1440"))  # 24 ч


def minutes_until_next_monday(now=None) -> int:
    """Минут до ближайшего понедельника 00:00 по времени колледжа (строго > 0).

    Ровно в понедельник 00:00 отвечает НЕДЕЛЮ, а не ноль: сессия, выданная в этот
    момент, иначе была бы мертворождённой."""
    from datetime import datetime, timedelta, timezone
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(timezone(timedelta(hours=COLLEGE_UTC_OFFSET_H)))
    days_ahead = (7 - local.weekday()) % 7 or 7          # weekday(): понедельник = 0
    boundary = (local + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((boundary - local).total_seconds() // 60))


def issue_ttl_min(client: str, now=None) -> int:
    """Сколько минут жить ТОЛЬКО ЧТО выдаваемой сессии.

    ⚠️ Не путать с `session_ttl_min` — это РАЗНЫЕ величины, и их разделение
    принципиально. Здесь — конкретный срок конкретной сессии, он вычисляется ОДИН РАЗ
    при входе и дальше живёт в auth_sessions.expires_at. Там — потолок ПОЛИТИКИ,
    постоянный.

    Считать «до понедельника» на каждом обновлении токена нельзя: в понедельник
    утром формула вернула бы «ещё неделя», возраст недельной сессии оказался бы меньше
    нового потолка, и она продлилась бы сама собой. Сессия не кончалась бы никогда —
    ровно та же болезнь, что в 3.5.5, только с другого конца."""
    if (client or "").strip().lower() != "android":
        return JWT_TTL_MIN
    return max(JWT_MOBILE_FLOOR_MIN, minutes_until_next_monday(now))


def session_ttl_min(client: str) -> int:
    """Потолок ПОЛИТИКИ в минутах для клиента ('android' | 'web' | '').

    Проверяется на каждом /auth/refresh против реального возраста сессии. Величина
    постоянна намеренно: она защищает от того, что однажды уже случилось (3.5.5) —
    токен, выданный при прежней, более щедрой настройке, продолжал обновляться по ней
    же ещё месяц после того, как настройку ужесточили. Потолок обязан считаться от
    ТЕКУЩЕЙ политики, а не от той, что действовала при выдаче.

    Для мобильного это неделя — верхняя граница `issue_ttl_min`: больше недели до
    ближайшего понедельника не бывает."""
    return JWT_MOBILE_TTL_MIN if (client or "").strip().lower() == "android" else JWT_TTL_MIN

#CORS: какие сайты-источники могут обращаться к API из браузера.
#Десктопу CORS не нужен (это не браузер). Для будущего сайта укажите его домен,
#напр. GRADEBOOK_ALLOWED_ORIGINS="https://journal.vsgutu.ru". По умолчанию "*"
#(удобно для разработки; для прод-сайта лучше сузить до конкретного домена).
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("GRADEBOOK_ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]


#Признак «бой» — суженный CORS (то же правило, по которому main.py прячет /docs).
#Отдельной переменной GRADEBOOK_ENV не заводим: она немедленно разъехалась бы с
#ALLOWED_ORIGINS, и «бой» получился бы двух сортов.
IS_PROD = ALLOWED_ORIGINS != ["*"]


def assert_production_secrets() -> list:
    """Проверка боевых секретов при старте. Возвращает список НЕсмертельных замечаний.

    🔒 Сервер, подписывающий токены ИЗВЕСТНЫМ ВСЕМ ключом, — это не «неоптимальная
    настройка», а открытая дверь: любой, кто видел исходники (а они у команды и у
    покупателя), выпускает себе токен с ролью admin и получает журнал целиком. Поэтому
    здесь именно ОТКАЗ ЗАПУСКАТЬСЯ, а не предупреждение в логе: упавший сервер чинят за
    минуты, а тихо работающий с dev-ключом не чинят никогда — о нём не знают.
    Проверка включается только на бою (см. IS_PROD): в разработке дефолт удобен и
    безопасен, там нет ни ПДн, ни внешнего доступа.

    Всё остальное (шифрование БД, ключи пушей) — предупреждения: без них продукт
    деградирует, но не становится дырявым, и останавливать колледж из-за выключенных
    уведомлений нельзя.
    """
    if IS_PROD and JWT_SECRET == DEV_JWT_SECRET:
        raise RuntimeError(
            "GRADEBOOK_JWT_SECRET не задан: сервер подписывал бы токены общеизвестным "
            "ключом из исходников, и любой смог бы выпустить себе админский вход. "
            "Задайте длинную случайную строку в server/.env и перезапустите."
        )
    warnings = []
    if IS_PROD and not DB_KEY:
        warnings.append("GRADEBOOK_DB_KEY не задан — файл базы с ПДн лежит "
                        "НЕзашифрованным (152-ФЗ, см. server/encrypt_db.py)")
    if IS_PROD and len(JWT_SECRET) < 32:
        warnings.append("GRADEBOOK_JWT_SECRET короче 32 символов — подпись токенов "
                        "перебираема, замените длинной случайной строкой")
    return warnings


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

#Адрес сайта для ССЫЛОК В ПИСЬМАХ. Берём тот же источник, что и WebAuthn: он уже обязан
#совпадать с реальным origin (иначе passkey не работают), значит второго места, которое
#можно забыть обновить при смене домена, мы не заводим.
#⚠️ В письме адрес обязан быть АБСОЛЮТНЫМ и https: относительная ссылка в почтовом
#клиенте не откроется вовсе, а http отдал бы одноразовый токен сброса в открытый канал.
SITE_URL = (os.environ.get("GRADEBOOK_SITE_URL", "").strip() or WEBAUTHN_ORIGIN).rstrip("/")

#Сколько живёт ссылка восстановления пароля. Полчаса — компромисс: человек успевает
#дойти до почты, а украденное или забытое в общем почтовом ящике письмо перестаёт быть
#ключом от аккаунта уже к концу пары.
PASSWORD_RESET_TTL_MIN = int(os.environ.get("GRADEBOOK_PASSWORD_RESET_TTL_MIN", "30"))


#RuStore Push. Секреты — ТОЛЬКО из окружения (.env вне git): сервисный токен даёт право
#рассылать уведомления всем пользователям приложения, утечка = чужая рассылка от нашего
#имени. Пусто — пуши просто выключены, сервер работает как раньше.
RUSTORE_PROJECT_ID = os.environ.get("GRADEBOOK_RUSTORE_PROJECT_ID", "").strip()
RUSTORE_SERVICE_TOKEN = os.environ.get("GRADEBOOK_RUSTORE_SERVICE_TOKEN", "").strip()
#Сколько дней держим токен устройства без подтверждения. Приложение подтверждает токен
#при каждом запуске; молчит дольше — считаем, что программу удалили.
PUSH_TOKEN_TTL_DAYS = int(os.environ.get("GRADEBOOK_PUSH_TOKEN_TTL_DAYS", "90"))


def push_enabled() -> bool:
    """Настроены ли пуши. Проверяем ЯВНО, а не по факту ошибки при отправке: без этого
    каждый выставленный балл порождал бы бесполезный сетевой запрос и запись в лог."""
    return bool(RUSTORE_PROJECT_ID and RUSTORE_SERVICE_TOKEN)


#GIF-пикер мессенджера (Klipy) — фиксированный инфраструктурный ключ на всё
#развёртывание (не выбор ИИ-провайдера, поэтому НЕ в /web/admin/ai-config, тот же
#принцип, что у RuStore выше). Пусто — пикер выключен, чат работает как раньше.
KLIPY_API_KEY = os.environ.get("GRADEBOOK_KLIPY_API_KEY", "").strip()
