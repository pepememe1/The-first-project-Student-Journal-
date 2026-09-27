// peerProfileLinks.test.mjs — карточка собеседника и «Поделиться контактом»
// (аудит 22.09.2026: F-17, F-18).
//
// F-17: ответ по прежнему собеседнику, пришедший позже, ложился в карточку нового — на
// экране чужие ФИО и кнопки. F-18: ссылка несла адрес 127.0.0.1 программы и РОЛЬ
// отправителя, а `?peer=` не читал никто — по ней открывался просто мессенджер.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `location.origin` в ссылку — краснеет «адрес
// программы не уходит»; убрать сверку поколения — краснеет F-17. Маршрут `/messages`,
// возврат после входа и `?peer=` — в `deepLinks.test.mjs`.
import { test, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

function memoryStorage() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
  }
}
globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage }

const { publicSiteOrigin } = await import('../src/api/server.js')

afterEach(() => { localStorage.clear(); delete globalThis.location })

test('F-18: из программы в ссылку уходит адрес сайта, а не 127.0.0.1', () => {
  globalThis.location = { origin: 'http://127.0.0.1:53211' }
  assert.equal(publicSiteOrigin(), 'https://esstu-gradebook.ru')
})

test('F-18: из телефона — тоже адрес сервера, а не https://localhost', () => {
  globalThis.location = { origin: 'https://localhost' }
  assert.equal(publicSiteOrigin(), 'https://esstu-gradebook.ru')
})

test('F-18: сервер, заданный вручную, главнее встроенного', () => {
  globalThis.location = { origin: 'http://127.0.0.1:53211' }
  localStorage.setItem('gb.api_base', 'https://journal.college.example/')
  assert.equal(publicSiteOrigin(), 'https://journal.college.example')
})

test('F-18: на сайте адрес страницы и есть публичный', () => {
  globalThis.location = { origin: 'https://esstu-gradebook.ru' }
  assert.equal(publicSiteOrigin(), 'https://esstu-gradebook.ru')
})

const card = readFileSync(new URL('../src/components/messenger/PeerProfileCard.vue', import.meta.url), 'utf8')

test('F-18: ссылка — публичный адрес и путь без роли', () => {
  const share = card.slice(card.indexOf('async function shareContact()'))
  //Строка, которая СОБИРАЕТ ссылку, — не комментарий рядом (там прежний вид назван словами).
  const linkLine = share.split('\n').find((l) => l.trim().startsWith('const link ='))
  assert.ok(linkLine, 'не нашли сборку ссылки')
  assert.match(linkLine, /publicSiteOrigin\(\)\}\/messages\?peer=/)
  assert.doesNotMatch(linkLine, /location\.origin/, 'в ссылку снова уходит адрес программы')
  //Маршрут `/messages`, возврат после входа и разбор `?peer=` — ПОВЕДЕНИЕМ в
  //`deepLinks.test.mjs` (прежние регулярки здесь пропустили потерю ссылки при входе).
})

test('F-17: ответ по прежнему собеседнику не ложится в карточку нового', () => {
  const load = card.slice(card.indexOf('async function loadPeer()'), card.indexOf('onMounted(loadPeer)'))
  assert.match(load, /const gen = \+\+peerGen/)
  assert.match(load, /if \(gen === peerGen\) fetched\.value = data\.profile/,
    'ответ принимается без сверки поколения')
  assert.match(load, /fetched\.value = null\n/, 'до ответа карточка показывает прежнего человека')
  assert.match(card, /watch\(\(\) => props\.userId, loadBlocked\)/,
    'статус блокировки не перечитывается при смене собеседника')
})
