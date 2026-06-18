# GradeBookAI — Подробный гайд: сервер, запуск, доступ из любой сети

Здесь по-честному и подробно: как это работает, как запустить, почему бывают
ошибки, бесплатные способы открыть сервер наружу, как подключается чужой ПК на
другом интернете и какой именно адрес вводит админ.

---

## 0. Частые вопросы (коротко)

**Почему `server/app/__init__.py` пустой?**
Это нормально. Файл `__init__.py` нужен Python, чтобы считать папку `app`
**пакетом** — тогда работают импорты вида `from app.main import app` и
`from .db import init_db`. Содержимого ему не требуется (у нас там только строка-
докстринг). Пустой `__init__.py` — стандартная практика, это не ошибка.

**Почему ошибка при запуске `main.py` напрямую?**
Если запустить `python server/app/main.py` (или кнопкой «Run» по файлу), будет:
```
ImportError: attempted relative import with no known parent package
```
Причина: `main.py` использует **относительные импорты** (`from .db import ...`,
`from .routers import auth`). Они работают, только когда модуль запущен как часть
пакета `app`, а не как одиночный скрипт. Запуск файла напрямую делает его
`__main__` без пакета → импорты ломаются.

**Как правильно запускать** (из папки `server`):
```bash
cd server
python run.py
# или то же самое:
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Ключевое: команду давать ИЗ папки `server`, тогда `app` виден как пакет.

---

## 1. Как это работает

```
        PostgreSQL (приватно, на сервере; в интернет НЕ выставляется)
              ▲  только локально
        Бэкенд-API (FastAPI) ── наружу по HTTPS ──┐
              ▲                                    │
        HTTPS + JWT                          HTTPS + JWT
        Десктоп-прога (offline-first)        Сайт (в будущем)
```

- Прога работает **офлайн** на локальном SQLite. Появилась сеть и задан адрес
  сервера — фоновый поток синхронизируется через API (push свои изменения, pull
  чужие). Нет сети — спокойно ждёт. Это и есть offline-first (киллер-фича).
- Клиенты знают только **адрес API**, не пароль БД. Доступ — по логину/паролю
  (JWT), роли admin/teacher/student.
- Наружу торчит **только API**. PostgreSQL слушает localhost на сервере.

---

## 2. Запуск для разработки (на своём ПК, без настройки БД)

По умолчанию БД — файл SQLite (ничего ставить не надо):
```bash
pip install -r server/requirements.txt
cd server
python run.py
```
Проверка в браузере:
- http://localhost:8000/health → `{"status":"ok"}`
- http://localhost:8000/docs → интерактивная документация всех эндпоинтов.

---

## 3. Как стать администратором

Админ создаётся ОДИН раз. Способы:

**А. Через прогу (штатно).** Рядом с программой положи `api_config.json`:
```json
{ "api_url": "http://localhost:8000" }
```
Запусти прогу → войди логином `admin` → задай пароль (первый запуск). При первой
синхронизации прога сама создаст админа на сервере теми же кредами.

**Б. Вручную (проверить сервер).** Через http://localhost:8000/docs → эндпоинт
`POST /auth/bootstrap-admin`, или командой:
```bash
curl -X POST http://localhost:8000/auth/bootstrap-admin ^
  -H "Content-Type: application/json" ^
  -d "{\"login\":\"admin\",\"password\":\"ПарольМин8\",\"full_name\":\"Администратор\"}"
```
Повторный вызов вернёт 409 (админ уже есть) — это нормально и безопасно.

Дальше админ в проге заводит преподавателей/студентов (каждому — логин и пароль).
Они синхронизируются на сервер; эти люди входят со своих ПК своими кредами.

---

## 4. Какой адрес вводит админ (важно!)

«Адрес сервера» = **базовый URL API**, по которому сервер виден тому ПК.
- **В одной локальной сети:** `http://192.168.1.50:8000` (IP сервера в сети).
  Снаружи, из другого интернета, такой адрес НЕ работает.
- **Из любого интернета:** нужен ПУБЛИЧНЫЙ адрес —
  `https://ваш-домен` или `https://xxxx.trycloudflare.com` (бесплатный туннель,
  раздел 6) или `http://ПУБЛИЧНЫЙ_IP:8000`.

Куда вводить адрес (любой из трёх вариантов):
1. файл `api_config.json` рядом с программой: `{"api_url":"https://адрес"}`;
2. в проге: админ-панель → «База данных» → «Сервер синхронизации (API)»;
3. зашить в сборку: `app_settings.DEFAULT_API_URL = "https://адрес"` (тогда
   клиентам вообще ничего вводить не надо).

Пустой адрес = офлайн-режим без сервера (прога работает только локально).

---

## 5. Как данные подтягиваются на ЧУЖОМ ПК (на другом интернете)

Пошагово, что происходит у друга в другом городе:
1. У друга стоит прога, в `api_config.json` — **публичный** адрес сервера.
2. Админ заранее создал другу учётку (преподаватель/студент) — она ушла на
   сервер при синхронизации админского ПК.
3. Друг запускает прогу, вводит свои логин/пароль. Прога:
   - проверяет вход локально (offline-first), а в фоне логинится к API (получает
     JWT);
   - фоновый поток делает `pull` → забирает с сервера студентов, преподавателей,
     группы, занятия, оценки → пишет в свой локальный SQLite;
   - свои изменения отправляет `push`.
4. Друг видит данные. Дальше работает даже без интернета; появится сеть —
   до-синхронизируется.

То есть «другой интернет» не важен — важно, чтобы адрес сервера был **публично
доступен** (раздел 6 — как сделать бесплатно).

---

## 6. Бесплатные способы открыть сервер наружу

> ⚠️ Важно про 152-ФЗ: бесплатные туннели (Cloudflare/ngrok) идут через
> зарубежные серверы. Это ОК для **теста с другом на учебных/выдуманных данных**,
> но НЕ для боевых персональных данных студентов. Для боевой эксплуатации —
> только сервер в РФ (раздел 7).

### 6.1. Cloudflare Tunnel (рекомендую, бесплатно, без «белого IP»)
Туннель сам соединяется наружу от твоей машины — не нужны проброс портов и
публичный IP (работает даже за роутером/CGNAT). Даёт адрес `https://...`.

1. Скачать `cloudflared` (Windows: с офсайта Cloudflare, один .exe).
2. Запустить бэкенд: `cd server && python run.py` (слушает :8000).
3. В другом окне:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
   Он напечатает адрес вида `https://random-words.trycloudflare.com`.
4. Этот адрес и есть `api_url`. Дай его другу (в `api_config.json`).
   - Быстрый режим выше даёт ВРЕМЕННЫЙ адрес (меняется при перезапуске).
   - Постоянный адрес (свой домен) — бесплатно через аккаунт Cloudflare +
     `cloudflared tunnel create` + DNS-запись (named tunnel).

### 6.2. ngrok (просто, бесплатно)
1. Зарегистрироваться на ngrok, поставить, прописать authtoken.
2. `ngrok http 8000` → выдаст `https://xxxx.ngrok-free.app`.
3. Это `api_url`. На бесплатном тарифе адрес меняется при каждом запуске.

### 6.3. localhost.run / serveo (без установки, по SSH)
```bash
ssh -R 80:localhost:8000 localhost.run
```
Выдаст временный публичный URL. Удобно для разовой проверки, бывает нестабильно.

### 6.4. Дом/колледж: «белый IP» + бесплатный домен (если есть публичный IP)
Если у ПК есть публичный IP и доступ к роутеру:
- проброс порта 8000 (или 443) на этот ПК;
- бесплатный домен через DuckDNS (`*.duckduckgo`-подобный поддомен бесплатно);
- бесплатный сертификат Let's Encrypt (certbot) для HTTPS.
⚠️ У многих провайдеров в РФ «серый» IP (CGNAT) — проброс не сработает, тогда
только туннель (6.1/6.2).

### 6.5. Бесплатные облачные ВМ
Есть бесплатные/триальные ВМ (например, Always Free у некоторых облаков), но они
обычно вне РФ и требуют привязку карты — для боевых ПДн не подходят (152-ФЗ).
Для теста — на твой выбор.

---

## 7. Боевой режим: сервер в РФ + HTTPS (для реальных данных)

VPS в РФ (Timeweb / Selectel / Yandex Cloud / VK Cloud / Reg.ru), публичный
адрес, HTTPS. PostgreSQL — на той же ВМ, слушает localhost.

### 7.1. БД
```bash
sudo apt update && sudo apt install -y python3-venv postgresql nginx
sudo -u postgres psql -c "CREATE DATABASE vsgutu_grades;"
sudo -u postgres psql -c "CREATE USER vsgutu_user WITH PASSWORD 'СИЛЬНЫЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE vsgutu_grades TO vsgutu_user;"
```

### 7.2. Приложение
```bash
cd /opt && git clone <репозиторий> gradebook && cd gradebook/server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # отредактировать:
#   GRADEBOOK_DB_URL=postgresql://vsgutu_user:СИЛЬНЫЙ_ПАРОЛЬ@localhost:5432/vsgutu_grades
#   GRADEBOOK_JWT_SECRET=<openssl rand -hex 32>
#   GRADEBOOK_ALLOWED_ORIGINS=https://ваш-домен   (когда появится сайт)
```

### 7.3. Автозапуск (systemd) — `/etc/systemd/system/gradebook.service`
```ini
[Unit]
Description=GradeBookAI API
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/gradebook/server
EnvironmentFile=/opt/gradebook/server/.env
ExecStart=/opt/gradebook/server/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now gradebook
```

### 7.4. nginx + HTTPS (Let's Encrypt) — `/etc/nginx/sites-available/gradebook`
```nginx
server {
    server_name ваш-домен;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/gradebook /etc/nginx/sites-enabled/
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d ваш-домен
sudo ufw allow 80,443/tcp && sudo ufw enable
```
Теперь API на `https://ваш-домен`. В прогах `api_url = https://ваш-домен`.

### 7.5. Чек-лист безопасности (152-ФЗ)
- Сервер и БД — в РФ. Наружу только 80/443; PostgreSQL — localhost.
- `GRADEBOOK_JWT_SECRET` — длинный случайный (не дефолт).
- HTTPS обязателен. `.env` не коммитить. Пароль БД сильный.
- Бэкапы PostgreSQL по расписанию (`pg_dump`).

---

## 8. Как «подключиться к этой штуке» (сводка точек доступа)

После запуска (локально или по публичному адресу `BASE`):
- `GET  BASE/health` — жив ли сервер.
- `GET  BASE/docs` — вся документация и ручная проверка из браузера.
- `POST BASE/auth/bootstrap-admin` — создать первого админа.
- `POST BASE/auth/login` — вход, отдаёт JWT.
- `GET  BASE/sync/pull?since=` — забрать изменения.
- `POST BASE/sync/push` — отправить изменения (нужен заголовок
  `Authorization: Bearer <токен>`).

Десктоп всё это делает сам: ты только задаёшь `api_url` и входишь логином/паролем.

## 9. Сайт «для всех» (следующая фаза)
Сайт сядет на ТОТ ЖЕ API: те же логины/пароли (JWT), роли. Реализуем отдельно
(Фаза 4). В CORS укажем домен сайта (`GRADEBOOK_ALLOWED_ORIGINS`).
