/**
 * client.js — HTTP-клиент к тому же REST API, что и десктоп (порт идей sync_client).
 *
 * База пустая ('') → запросы идут на ТОТ ЖЕ origin, что и сайт. На бою Caddy отдаёт
 * SPA в корне домена и проксирует /auth, /me, /web, ... в FastAPI — поэтому «адрес
 * сервера = адрес сайта» выполняется само собой, и CORS не нужен (same-origin).
 * В dev проксирование делает vite.config.js. Переопределить базу можно через
 * VITE_API_BASE (например, чтобы фронт смотрел на удалённый сервер).
 *
 * Интерсепторы:
 *   • запрос — подставляют Authorization: Bearer <access>, X-Device-Id, X-Client: web;
 *   • ответ  — на 401 один раз пытаются тихо обновить access через /auth/refresh
 *     (как десктопный клиент), затем повторяют исходный запрос. Не вышло — сигналим
 *     «сессия истекла» (обработчик регистрирует App → редирект на /login).
 */
import axios from 'axios'
import { getAccess, getRefresh, setTokens, clearTokens, getDeviceId } from './tokens'
import { isCacheable, writeCache, readCache, servingStale } from './offlineCache'
import { getApiBase } from './server'

export const api = axios.create({
  baseURL: getApiBase(),
  timeout: 20000,
})

// Обработчик «сессия истекла» регистрирует App (чтобы не тянуть сюда router и не плодить циклы).
let authExpiredHandler = null
export function setAuthExpiredHandler(fn) {
  authExpiredHandler = fn
}

api.interceptors.request.use((config) => {
  // Адрес сервера берём динамически на КАЖДЫЙ запрос: в приложении он задаётся в
  // рантайме (экран подключения), поэтому не фиксируем его при создании клиента.
  config.baseURL = getApiBase()
  const token = getAccess()
  if (token) config.headers.Authorization = `Bearer ${token}`
  config.headers['X-Device-Id'] = getDeviceId()
  config.headers['X-Client'] = 'web'
  return config
})

// Чтобы параллельные запросы не стартовали несколько refresh разом — общий промис.
let refreshing = null

async function doRefresh() {
  const refresh = getRefresh()
  if (!refresh) throw new Error('no refresh token')
  // Голый axios (без интерсепторов), чтобы не зациклиться на 401.
  const { data } = await axios.post(
    getApiBase() + '/auth/refresh',
    { refresh_token: refresh },
    { headers: { 'X-Device-Id': getDeviceId(), 'X-Client': 'web' } },
  )
  setTokens({ access: data.access_token, refresh: data.refresh_token || refresh })
  return data.access_token
}

// Успешный ответ: кэшируем role-scoped READ (GET /web/*, /me/prefs) для оффлайна.
function isGet(config) { return (config?.method || 'get').toLowerCase() === 'get' }

api.interceptors.response.use(
  (resp) => {
    const config = resp.config || {}
    if (isGet(config) && isCacheable(config.url)) {
      writeCache(config, resp.data)
      servingStale.value = false     // пришли свежие данные — мы онлайн
    }
    return resp
  },
  async (error) => {
    const { response, config } = error
    // Нет ответа (сеть недоступна/таймаут): для кэшируемых GET отдаём СОХРАНЁННОЕ —
    // экран показывает данные, а не пустоту. Обновятся, как только вернётся сеть.
    if (!response && config && isGet(config) && isCacheable(config.url)) {
      const hit = readCache(config)
      if (hit) {
        servingStale.value = true
        return Promise.resolve({
          data: hit.data, status: 200, statusText: 'OK (offline cache)',
          headers: { 'x-gb-stale': '1' }, config, request: null, cached: true,
        })
      }
    }
    if (!response || response.status !== 401 || config._retried) {
      return Promise.reject(error)
    }
    // Логин/refresh сами по себе не рефрешим — иначе бесконечный цикл.
    if (config.url?.includes('/auth/login') || config.url?.includes('/auth/refresh')) {
      return Promise.reject(error)
    }
    try {
      if (!refreshing) refreshing = doRefresh().finally(() => { refreshing = null })
      const newAccess = await refreshing
      config._retried = true
      config.headers.Authorization = `Bearer ${newAccess}`
      return api(config)
    } catch {
      clearTokens()
      if (authExpiredHandler) authExpiredHandler()
      return Promise.reject(error)
    }
  },
)
