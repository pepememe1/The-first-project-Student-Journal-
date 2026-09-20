// cacheOwner.test.mjs — офлайн-кэш принадлежит тому, кто запрашивал (находка ревью O03,
// 18.09.2026; починено 20.09.2026).
//
// ━━ ЧТО БЫЛО ━━
// `writeCache` спрашивал логин В МОМЕНТ ЗАПИСИ, а ответ приходит позже отправки. На
// общем компьютере колледжа этого хватает: пока GET за журналом A шёл по сети, A вышел
// и вошёл B — и данные A ложились в кэш B. В офлайне B открывал экран и видел чужие
// оценки как свои, причём выглядело это совершенно штатно.
//
// ━━ ПОЧЕМУ МЕТКА СТАВИТСЯ НА ОТПРАВКЕ ━━
// На приёме спросить «чей это ответ» уже не у кого: состояние сменилось. Знает об этом
// только сам запрос, поэтому `client.js` помечает его владельцем и поколением сессии.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть в `offlineCache.writeCache` `currentLogin()` вместо
// `config.__owner` — краснеет первый тест; убрать `ownsResponse` из интерцептора —
// второй.
import { test } from 'node:test'
import assert from 'node:assert/strict'

function memoryStorage() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size },
    _dump: () => [...m.keys()],
  }
}

globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage, addEventListener() {} }

const cache = await import('../src/api/offlineCache.js')

const loginAs = (login) =>
  localStorage.setItem('gb.user', JSON.stringify({ login, role: 'student' }))

test('ответ, помеченный владельцем, ложится ему, а не тому, кто вошёл позже', () => {
  loginAs('alice')
  const config = { url: '/web/student/overview', method: 'get', __owner: 'alice' }

  loginAs('bob')                               //пока ответ шёл, вошёл другой человек
  cache.writeCache(config, { avg: 4.9, name: 'Алиса' })

  const keys = localStorage._dump().filter((k) => k.includes('/web/student/overview'))
  assert.equal(keys.length, 1, `ожидалась одна запись кэша, есть: ${keys.join(', ')}`)
  assert.ok(keys[0].includes('alice'), `кэш записан не владельцу: ${keys[0]}`)
  assert.ok(!keys[0].includes('bob'), 'данные Алисы попали в кэш Боба')
})

test('чтение кэша тоже идёт по владельцу запроса, а не по текущему логину', () => {
  loginAs('alice')
  const config = { url: '/web/student/journal', method: 'get', __owner: 'alice' }
  cache.writeCache(config, { rows: [1, 2, 3] })

  loginAs('bob')
  //У Боба своего кэша нет: он не должен подобрать чужой по «текущему» логину.
  const asBob = cache.readCache({ url: '/web/student/journal', method: 'get', __owner: 'bob' })
  assert.equal(asBob, null, 'Боб прочитал кэш Алисы')

  //А владелец свой кэш по-прежнему получает.
  const asAlice = cache.readCache(config)
  assert.ok(asAlice && asAlice.data, 'владелец потерял собственный кэш')
  assert.deepEqual(asAlice.data.rows, [1, 2, 3])
})

test('без метки владельца поведение прежнее — модуль годится и вне нашего интерцептора', () => {
  loginAs('carol')
  cache.writeCache({ url: '/web/student/zet', method: 'get' }, { zet: 12 })
  const hit = cache.readCache({ url: '/web/student/zet', method: 'get' })
  assert.ok(hit && hit.data.zet === 12)
})
