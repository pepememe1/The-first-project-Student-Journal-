// offlineCacheScope.test.mjs — ЧТО именно оседает на устройстве в оффлайн-кэше
// (web/src/api/offlineCache.js).
//
// Сторож заведён по итогам разбора безопасности мобильной версии 21.08.2026. Правило
// «кэшируем всё, что начинается на /web/» тихо захватило две вещи, которых там быть не
// должно: `/web/messenger/*` (ТЕЛА СООБЩЕНИЙ и каталог людей с ФИО) и `/web/admin/*`
// (справочники студентов целиком). Про мессенджер это ещё и отменяло решение, принятое
// в другом месте: он сознательно оставлен вне offline-first и вне SYNC_MODELS (§5.4).
//
// Проверяем СВОЙСТВО (запрет главнее разрешения), а не список: слепок списка краснел бы
// на каждом законном добавлении экрана и подталкивал бы «просто обновить ожидание».
import { test } from 'node:test'
import assert from 'node:assert/strict'

function memoryStorage() {
  const store = {}
  const api = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: (k) => { delete store[k] },
    clear: () => { for (const k of Object.keys(store)) delete store[k] },
  }
  return new Proxy(api, {
    get: (t, p) => (p in t ? t[p] : store[p]),
    set: (t, p, v) => { store[p] = String(v); return true },
    has: (t, p) => p in t || p in store,
    ownKeys: () => Reflect.ownKeys(store),
    getOwnPropertyDescriptor: (t, p) => ({ value: store[p], enumerable: true, configurable: true }),
  })
}

globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage }

const cache = await import('../src/api/offlineCache.js')

test('переписка НИКОГДА не кладётся на устройство', () => {
  for (const url of [
    '/web/messenger/chats',
    '/web/messenger/chats/direct:a|b/messages',
    '/web/messenger/users?role=student',
    '/web/messenger/users/stud:ivanov/profile',
  ]) {
    assert.equal(cache.isCacheable(url), false, `на диск не должно уходить: ${url}`)
  }
})

test('админские справочники НИКОГДА не кладутся на устройство', () => {
  for (const url of ['/web/admin/students', '/web/admin/groups', '/web/admin/messenger/reports']) {
    assert.equal(cache.isCacheable(url), false, `на диск не должно уходить: ${url}`)
  }
})

test('то, ради чего кэш и заведён, кэшируется по-прежнему', () => {
  for (const url of [
    '/web/student/overview',
    '/web/student/journal',
    '/web/teacher/journal',
    '/web/schedule',
    '/me/prefs',
  ]) {
    assert.equal(cache.isCacheable(url), true, `оффлайн-экран потерял кэш: ${url}`)
  }
})

test('запрет действует и на абсолютный адрес (база сервера задаётся в рантайме)', () => {
  //В приложении запросы уходят на явный адрес сервера, а не на тот же origin.
  assert.equal(cache.isCacheable('https://esstu-gradebook.ru/web/messenger/chats'), false)
  assert.equal(cache.isCacheable('https://esstu-gradebook.ru/web/student/overview'), true)
})

test('уже осевшая переписка вычищается с устройства разовой уборкой', () => {
  localStorage.clear()
  //Так выглядел кэш до правки: ключ «gb.cache.<логин>|<путь>».
  localStorage.setItem('gb.cache.ivanov|/web/messenger/chats', '{"data":[]}')
  localStorage.setItem('gb.cache.ivanov|/web/messenger/chats/c1/messages', '{"data":[]}')
  localStorage.setItem('gb.cache.ivanov|/web/admin/students', '{"data":[]}')
  localStorage.setItem('gb.cache.ivanov|/web/student/overview', '{"data":{}}')

  cache.purgeNeverCached()

  const left = Object.keys(localStorage).filter((k) => k.startsWith('gb.cache.'))
  assert.deepEqual(left, ['gb.cache.ivanov|/web/student/overview'],
    'уборка обязана снести переписку и админские данные и не тронуть журнал')
})
