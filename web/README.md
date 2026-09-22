# web/ — веб-редакция GradeBookAI (Vue 3 SPA) и Android-обёртка

Одна и та же SPA работает в трёх местах:

| где | кто отдаёт страницу | куда ходит за данными |
|---|---|---|
| сайт `esstu-gradebook.ru` | боевой Caddy (статика) + FastAPI | боевой сервер |
| десктопная программа | локальный сервер на `127.0.0.1` (`desktop/local_api.py`) | локальная копия; онлайн-разделы (мессенджер, одобрение машин, «Сервер» и др.) пересылаются на бой — список `_PROXY_PREFIXES` там же |
| Android (RuStore) | Capacitor из бандла на телефоне (`https://localhost`) | боевой сервер |

Отсюда главное правило: **всё, что задаёт сервер в заголовках ответа, в приложении не
действует** — CSP едет метой в `index.html` (держит `tests/cspMeta.test.mjs`).

> Прежний README (эпоха отдельного репозитория, июль 2026) — в
> `docs/done/outdated/WEB-README-2026-07.md`. Почти всё в нём уже неправда.

## Стек

Vue 3.5, Vite 8, Pinia 3, Vue Router 4, Tailwind 4, Axios, `@lucide/vue`, Capacitor 8.
Точные версии — `package.json`, а не этот файл.

## Команды

```bash
npm install
npm run dev        # http://localhost:5173
npm run lint       # ESLint 9 — ДО сборки: ловит обращение к ref из мёртвой зоны
npm run build      # сборка в web/dist
npm test           # node --test, без внешних раннеров
```

## Где что

| путь | что |
|---|---|
| `src/api/endpoints.js` | весь контракт с сервером; `client.js` — axios, `outbox.js` — офлайн-очередь |
| `src/router/index.js` | страницы ЛЕНИВЫМ импортом; статически только `AppShell`, `LoginPage`, `NotFoundPage` (держит `tests/routePrefetch.test.mjs`) |
| `src/stores/` | Pinia-сторы (вход, тема, мессенджер, Вектор, озвучка, голос, язык…) |
| `src/utils/` | чистые функции под тестами (геометрия колеса, итоги опроса, черновики…) — логику выносят сюда, внутри `.vue` её без браузера не проверить |
| `src/i18n/dictionaries.js` | три локали (ru/en/zh) |
| `build/stripHtmlComments.js` | вырезает комментарии из `index.html` при сборке. ⚠️ Каталог `build/` исключён из `.gitignore` поимённо — без этого файла `npm run build` на чистом клоне падает |
| `public/` | всё отсюда едет в бандл сайта, в OTA-бандл телефона и в .exe — вес здесь стоит втрое |
| `android/` | Capacitor-обёртка, виджет расписания, пуши RuStore |
| `deploy/release-ota.ps1` | выпуск OTA-бандла: собрать, упаковать, залить и проверить, что сайт отдаёт новую версию |

## Выкладка

- **Сайт** — из корня репозитория: `npm run build` здесь, затем `bash deploy/deploy-web.sh`.
- **Телефоны** — правки веба едут OTA (`deploy/release-ota.ps1 -Deploy`), перезалив APK в
  RuStore нужен только при смене НАТИВНОЙ части (`npx cap sync android`,
  `cd android && ./gradlew assembleRelease`, JDK 21, versionCode растёт на каждый перезалив).
- ⚠️ `deploy/Caddyfile` и `deploy/nginx.conf` — **образцы, не боевые конфиги** (так и
  написано в их первой строке). Боевой — `server/Caddyfile`, и он один.
- ⚠️ `deploy/update-vps.ps1` — старая обёртка над теми же `deploy/*.sh`; надёжнее звать
  скрипты напрямую из Git Bash.

## Грабли, которые уже стоили дорого

- **Внутри Capacitor service worker снимается** (`src/main.js`): он отдавал старую оболочку
  из кэша, и OTA-обновления месяц не доходили до телефонов при зелёных логах.
- **Ничего, что должен видеть веб-слой, не создавать в Android через `evaluateJavascript`** —
  любая загрузка документа создаёт `window` заново. Мост — только `addJavascriptInterface`.
- **`waitUntil: 'networkidle'` в живой проверке вешает прогон** — у SPA постоянный опрос и
  сокеты. Только `domcontentloaded` + явный `waitForSelector`.
- **Шрифт, названный в CSS, обязан лежать в `public/fonts/`** — внешние CDN шрифтов закрыты
  CSP боевого Caddy (152-ФЗ), браузер молча возьмёт следующий в стеке.

Полные правила проекта — в `CLAUDE.md` в корне (локальный файл, не в git) и в `README.md`
репозитория.
