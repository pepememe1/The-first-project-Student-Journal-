import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync } from 'node:fs'
//Плагин лежит отдельным файлом, чтобы его можно было проверить тестом, не
//поднимая весь Vite (web/tests/stripHtmlComments.test.mjs).
import stripHtmlComments from './build/stripHtmlComments.js'
//Метка сборки: по ней открытая вкладка узнаёт, что её код устарел после
//деплоя (см. src/utils/appVersion.js). Тоже отдельным файлом — под тест.
import buildStamp from './build/buildStamp.js'

// Во время разработки фронтенд крутится на своём порту (5173), а API — на 8000.
// Чтобы в dev всё выглядело как ОДИН адрес (как на бою за Caddy), проксируем
// известные API-префиксы на локальный FastAPI. Тогда в коде везде относительные
// пути (/auth/login, /web/...), и на проде тот же код работает без правок.
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000'
const API_PREFIXES = ['/auth', '/me', '/sync', '/admin', '/connect', '/web', '/health', '/docs', '/openapi.json']

// Выпуск продукта — из единственного места, desktop_update.APP_VERSION: по нему сервер
// узнаёт, на сколько выпусков отстало приложение (utils/appTag.js, server/app/client_app.py).
const GB_RELEASE = (readFileSync(new URL('../desktop_update.py', import.meta.url), 'utf8')
  .match(/^APP_VERSION = "Release ([\d.]+)"/m) || [])[1] || ''

export default defineConfig({
  plugins: [vue(), tailwindcss(), stripHtmlComments(), buildStamp()],
  define: { __GB_RELEASE__: JSON.stringify(GB_RELEASE) },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target: API_TARGET, changeOrigin: true }])
    ),
  },
})
