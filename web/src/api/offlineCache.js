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
 *
 * ⚠️ НО «роль вправе видеть» — это про ДОСТУП, а не про то, что стоит класть на диск.
 * Правило `/web/*` слишком широкое: под него попадали `/web/messenger/*` (ТЕЛА
 * СООБЩЕНИЙ, каталог людей с ФИО) и `/web/admin/*` (справочники студентов целиком).
 * Мессенджер сознательно оставлен вне offline-first и вне SYNC_MODELS (§5.4 CLAUDE.md) —
 * а это правило молча возвращало переписку на устройство, то есть отменяло решение,
 * принятое в другом месте и по другим соображениям. Оффлайн им обоим и не нужен:
 * переписка без сети бессмысленна (отправить нельзя), а справочники админ правит с
 * рабочего места. Поэтому ниже — явный список исключений; он ГЛАВНЕЕ разрешающего.
 * Держит web/tests/offlineCacheScope.test.mjs.
 */
import { ref } from 'vue'

const PREFIX = 'gb.cache.'
// Безопасные для оффлайна READ-префиксы.
const CACHEABLE = ['/web/', '/me/prefs']
// Что не кладём на диск НИКОГДА, даже подходя под правило выше (см. шапку файла).
// Порядок проверки: сначала запрет, потом разрешение.
const NEVER_CACHE = ['/web/messenger/', '/web/admin/']

// Глобальный флаг: последний показанный ответ пришёл из кэша (мы оффлайн). Компоненты
// (напр. шапка) могут показать «показаны сохранённые данные».
export const servingStale = ref(false)

/**
 * Счётчик записей в кэш. Нужен ровно для подписи «обновлено в 12:40» на экранах:
 * сама отметка времени лежит в localStorage, а Vue за ним не следит. Каждая удачная
 * запись двигает счётчик, и вычисляемые подписи пересчитываются.
 */
export const cacheVersion = ref(0)

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
  if (NEVER_CACHE.some((p) => url.includes(p))) return false
  return CACHEABLE.some((p) => url.startsWith(p) || url.includes(p))
}

export function writeCache(config, data) {
  // Блобы (xlsx-экспорт) и не-объекты не кэшируем — только JSON-данные экранов.
  if (config.responseType === 'blob' || data == null || typeof data !== 'object') return
  try {
    localStorage.setItem(`${PREFIX}${currentLogin()}|${reqKey(config)}`,
      JSON.stringify({ t: Date.now(), data }))
    cacheVersion.value += 1
  } catch { /* переполнена квота — не критично */ }
}

/**
 * Когда данные этого запроса последний раз приходили С СЕРВЕРА (мс) или 0.
 *
 * Именно «с сервера», а не «когда показали»: подпись под оценками должна отвечать на
 * вопрос «насколько это свежее», иначе она успокаивает вместо того, чтобы предупреждать.
 */
export function cachedAt(config) {
  return readCache(config)?.t || 0
}

export function readCache(config) {
  try {
    const raw = localStorage.getItem(`${PREFIX}${currentLogin()}|${reqKey(config)}`)
    return raw ? JSON.parse(raw) : null   // { t, data } | null
  } catch {
    return null
  }
}

/**
 * Самая свежая сохранённая копия ЛЮБОГО запроса, начинающегося с этого пути.
 *
 * Нужно там, где точные параметры запроса заранее неизвестны: расписание, например,
 * запрашивается то с группой, то без неё, то с категорией портала — а офлайн-Вектору
 * нужно просто «последнее известное расписание». Подбирать ключ по кусочкам значило бы
 * повторить сборку параметров ещё раз и однажды с ней разойтись.
 */
export function findCached(pathPrefix) {
  const head = `${PREFIX}${currentLogin()}|${pathPrefix}`
  let best = null
  try {
    for (const k of Object.keys(localStorage)) {
      if (!k.startsWith(head)) continue
      const hit = JSON.parse(localStorage.getItem(k) || 'null')
      if (hit && (!best || hit.t > best.t)) best = hit
    }
  } catch { /* битая запись — ведём себя как при её отсутствии */ }
  return best        // { t, data } | null
}

/** Полная очистка кэша (вызывается при выходе из аккаунта). */
/**
 * Разовая уборка того, что успело осесть до появления `NEVER_CACHE`.
 *
 * Без неё правило действует только на БУДУЩИЕ ответы, а уже сохранённая переписка
 * осталась бы лежать на устройстве до следующего выхода из аккаунта — то есть у части
 * людей навсегда. Обход ключей localStorage стоит доли миллисекунды, а выполнить его
 * надо ровно один раз на устройство, поэтому зовём при загрузке модуля.
 */
export function purgeNeverCached() {
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(PREFIX) && NEVER_CACHE.some((p) => k.includes(p)))
      .forEach((k) => localStorage.removeItem(k))
  } catch { /* нет localStorage (тесты в node) или приватный режим */ }
}

purgeNeverCached()

export function clearCache() {
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(PREFIX))
      .forEach((k) => localStorage.removeItem(k))
  } catch { /* */ }
  servingStale.value = false
}
