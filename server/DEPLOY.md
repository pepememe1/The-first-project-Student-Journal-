# GradeBookAI — Развёртывание сервера и доступ из любой сети

Здесь: как это работает, как запустить сервер, стать админом, дать другу
протестировать из другой сети, и как открыть сервер публично по HTTPS.

---

## 1. Как это работает (коротко)

```
PostgreSQL (приватно, на сервере)
      ▲
      │ только локально, в интернет НЕ выставляется
Бэкенд-API (FastAPI, HTTPS наружу)
      ▲                     ▲
   HTTPS+JWT            HTTPS+JWT
 Десктоп-прога          Сайт (в будущем)
```

- Десктоп работает **offline** на локальном SQLite. Когда есть сеть и задан
  адрес сервера — фоновый поток синхронизируется через API (push/pull).
- Клиенты знают только **адрес API** (не пароль БД). Авторизация — JWT, роли.
- Наружу открыт **только API по HTTPS**. PostgreSQL слушает локально на сервере
  и в интернет не выставляется — так безопаснее и правильно по 152-ФЗ.

**Важно про «одну сеть»:** десктоп работает через любую сеть. Чтобы друг из
другого города подключился, нужен **публичный адрес API** (домен/публичный IP +
HTTPS) — см. раздел 5. На LAN-адрес (192.168.x.x) снаружи не зайти.

---

## 2. Запуск сервера для разработки (на своём ПК, SQLite)

```bash
pip install -r server/requirements.txt
cd server
uvicorn app.main:app --reload --port 8000
```
Документация и ручная проверка: http://localhost:8000/docs

---

## 3. Как стать администратором

Админ создаётся **один раз**. Два способа:

**А. Через десктоп (штатно).** Запусти прогу с заданным адресом сервера
(`api_config.json` рядом с прогой: `{"api_url":"http://localhost:8000"}`), войди
логином `admin` → задай пароль (первый запуск). При первой синхронизации прога
сама создаст администратора на сервере (bootstrap) теми же кредами.

**Б. Вручную через API** (для проверки сервера):
```bash
curl -X POST http://localhost:8000/auth/bootstrap-admin \
  -H "Content-Type: application/json" \
  -d '{"login":"admin","password":"ВашПарольМин8","full_name":"Администратор"}'
```
Повторный вызов вернёт 409 — админ уже есть. Это безопасно.

Дальше админ в проге заводит преподавателей/студентов (у каждого логин+пароль) —
они синхронизируются на сервер, и эти люди входят со своих ПК.

---

## 4. Тест с другом из ДРУГОЙ сети

Другу нужен:
1. **Публичный адрес сервера** (раздел 5) — иначе из другой сети не достучаться.
2. **Своя учётка**: админ создаёт преподавателя/студента (логин+пароль), синк
   отправляет на сервер.
3. Друг: ставит прогу, кладёт рядом `api_config.json` с публичным адресом
   (`{"api_url":"https://ваш-домен"}`), запускает, входит своими логином/паролем.
   Данные подтянутся с сервера.

> Быстрый тест без аренды сервера: можно временно прокинуть локальный бэкенд в
> интернет через любой HTTPS-туннель (туннель-сервис даёт временный адрес вида
> `https://xxxx.tunnel`). Годится ТОЛЬКО для проверки, не для боевого режима, и в
> РФ часть туннелей может быть недоступна. Для реального доступа — раздел 5.

---

## 5. Публичный доступ по HTTPS (боевой режим, сервер в РФ)

Цель: сервер в РФ с публичным адресом и HTTPS. Шаги (на примере VPS в РФ —
Timeweb / Selectel / Yandex Cloud / VK Cloud / Reg.ru):

### 5.1. Сервер и БД
```bash
# на VPS (Ubuntu):
sudo apt update && sudo apt install -y python3-venv postgresql nginx
sudo -u postgres psql -c "CREATE DATABASE vsgutu_grades;"
sudo -u postgres psql -c "CREATE USER vsgutu_user WITH PASSWORD 'СИЛЬНЫЙ_ПАРОЛЬ';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE vsgutu_grades TO vsgutu_user;"
```
PostgreSQL оставляем слушать **localhost** (по умолчанию) — в интернет не открываем.

### 5.2. Приложение
```bash
cd /opt && git clone <репозиторий> gradebook && cd gradebook/server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # отредактировать:
#   GRADEBOOK_DB_URL=postgresql://vsgutu_user:СИЛЬНЫЙ_ПАРОЛЬ@localhost:5432/vsgutu_grades
#   GRADEBOOK_JWT_SECRET=<длинная случайная строка, напр. `openssl rand -hex 32`>
#   GRADEBOOK_ALLOWED_ORIGINS=https://ваш-домен   (когда появится сайт)
```

### 5.3. systemd-сервис (автозапуск)
`/etc/systemd/system/gradebook.service`:
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
Uvicorn слушает только 127.0.0.1 — наружу его публикует nginx с HTTPS.

### 5.4. nginx + HTTPS (Let's Encrypt)
`/etc/nginx/sites-available/gradebook`:
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
sudo certbot --nginx -d ваш-домен     # выпустит и подключит TLS-сертификат
sudo ufw allow 80,443/tcp && sudo ufw enable
```
Теперь API доступен по `https://ваш-домен`. В прогах ставим
`api_config.json: {"api_url":"https://ваш-домен"}` (или зашиваем в сборку
`app_settings.DEFAULT_API_URL`).

### 5.5. Чек-лист безопасности (152-ФЗ)
- Сервер и БД — **в РФ**.
- Наружу открыты только 80/443; PostgreSQL — localhost.
- `GRADEBOOK_JWT_SECRET` — длинный случайный, не дефолтный.
- HTTPS обязателен (через nginx/certbot).
- `.env` не коммитить; пароль БД — сильный.
- Бэкапы PostgreSQL (pg_dump по расписанию).

---

## 6. Сайт «открытый для всех» (следующая фаза)

Сайт пока не реализован, но архитектура уже готова: он будет работать через
**тот же API**. Варианты:
- статический фронт (HTML/JS) или серверные страницы (Jinja2), отдаваемые тем же
  nginx, и обращающиеся к `/auth` и `/sync`(или к новым REST-эндпоинтам);
- авторизация — те же логины/пароли (JWT), роли admin/teacher/student;
- для сайта в CORS укажем его домен (`GRADEBOOK_ALLOWED_ORIGINS`).

Это отдельный этап (Фаза 4 по нашему плану).
