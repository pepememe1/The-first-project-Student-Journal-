/**
 * offlineCache.js — оффлайн-доступ к данным (stale-while-revalidate).
 *
 * Идея (как offline-first в десктопе, только для ЧТЕНИЯ): каждый успешный GET к
 * role-scoped `/web/*` сохраняем локально. Когда сети нет — отдаём последнее
 * сохранённое, и приложение показывает данные, а не пустой экран. Есть сеть —
 * приходит свежий ответ и перезаписывает кэш.
 *
 * Хранилище — localStorage: работает и в браузере, и в Android-WebView (Capacitor).
 * Кэш привязан к ЛОГИНУ и полностью стирается при выходе (`clearCache`), чтобы на
 * общем устройстве данные одного пользователя не показались другому.
 *
 * Кэшируем только то, что роль и так вправе видеть (`/web/*`, `/me/prefs`). Пароли и
 * чужие данные сюда не попадают — сервер их и не отдаёт в этих ответах.
 */
import { ref } from 'vue'

const PREFIX = 'gb.cache.'
// Безопасные для оффлайна READ-префиксы.
const CACHEABLE = ['/web/', '/me/prefs']

// Глобальный флаг: последний показанный ответ пришёл из кэша (мы оффлайн). Компоненты
// (напр. шапка) могут показать «показаны сохранённые данные».
export const servingStale = ref(false)

function currentLogin() {
  try {
    return JSON.parse(localStorage.getItem('gb.user') || 'null')?.login || '_'
  } catch {
    return '_'
  }
}

/** Канонический ключ запроса: путь + отсортированные query-параметры. */
export function reqKey(config = {}) {
  const url = config.url || ''
  const p = config.params && Object.keys(config.params).length
    ? '?' + Object.keys(config.params).sort().map((k) => `${k}=${config.params[k]}`).join('&')
    : ''
  return url + p
}

export function isCacheable(url = '') {
  return CACHEABLE.some((p) => url.startsWith(p) || url.includes(p))
}

export function writeCache(config, data) {
  // Блобы (xlsx-экспорт) и не-объекты не кэшируем — только JSON-данные экранов.
  if (config.responseType === 'blob' || data == null || typeof data !== 'object') return
  try {
    localStorage.setItem(`${PREFIX}${currentLogin()}|${reqKey(config)}`,
      JSON.stringify({ t: Date.now(), data }))
  } catch { /* переполнена квота — не критично */ }
}

export function readCache(config) {
  try {
    const raw = localStorage.getItem(`${PREFIX}${currentLogin()}|${reqKey(config)}`)
    return raw ? JSON.parse(raw) : null   // { t, data } | null
  } catch {
    return null
  }
}

/** Полная очистка кэша (вызывается при выходе из аккаунта). */
export function clearCache() {
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(PREFIX))
      .forEach((k) => localStorage.removeItem(k))
  } catch { /* */ }
  servingStale.value = false
}
