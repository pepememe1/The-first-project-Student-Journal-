// drafts.test.mjs — черновики мессенджера на устройстве (web/src/utils/drafts.js).
//
// Сторож заведён по итогам разбора безопасности мобильной версии 21.08.2026. Прежняя
// реализация жила в сторе, ключевалась ТОЛЬКО id беседы и переживала выход из аккаунта:
// на общем телефоне следующий вошедший открывал общий канал и видел в поле ввода чужой
// недописанный текст. Проверяем именно это свойство, а не «черновик сохраняется».
//
// ⚠️ localStorage подставляем сам, как в outbox.test.mjs (node --test без браузера).
// Мок должен вести себя как настоящий и в обходе ключей: `Object.keys(localStorage)`
// обязан давать КЛЮЧИ, а не имена методов, — иначе уборка проверялась бы понарошку.
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
  //Методы прячем от перечисления, ключи держим в самом объекте — так Object.keys()
  //возвращает ровно то же, что у настоящего localStorage.
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

const drafts = await import('../src/utils/drafts.js')

function loginAs(login) {
  if (login) localStorage.setItem('gb.user', JSON.stringify({ login, role: 'student' }))
  else localStorage.removeItem('gb.user')
}

test('черновик одного пользователя не виден другому в ТОЙ ЖЕ беседе', () => {
  localStorage.clear()
  const channel = 'sys:announce:К74/1'      //общий канал: id у обоих одинаковый

  loginAs('ivanov')
  drafts.saveDraft(channel, 'занял денег у старосты, отдам в пятницу')
  assert.equal(drafts.draftFor(channel), 'занял денег у старосты, отдам в пятницу')

  loginAs('petrov')
  assert.equal(drafts.draftFor(channel), '',
    'чужой черновик в общем канале виден следующему вошедшему')

  //И свой у первого при этом на месте — разделение, а не общая уборка.
  loginAs('ivanov')
  assert.equal(drafts.draftFor(channel), 'занял денег у старосты, отдам в пятницу')
})

test('выход стирает черновики ВСЕХ, кто писал на этом устройстве', () => {
  localStorage.clear()
  loginAs('ivanov')
  drafts.saveDraft('conv-1', 'первый')
  loginAs('petrov')
  drafts.saveDraft('conv-2', 'второй')

  drafts.clearDrafts()

  assert.deepEqual(Object.keys(localStorage).filter((k) => k.startsWith('gb.drafts.')), [],
    'после выхода на устройстве не должно остаться ни одной карты черновиков')
  loginAs('ivanov')
  assert.equal(drafts.draftFor('conv-1'), '')
})

test('карта старого формата (gb_msg_drafts) удаляется при первом же обращении', () => {
  localStorage.clear()
  //Так выглядело хранилище до правки: ничьё, переживает выход.
  localStorage.setItem('gb_msg_drafts', JSON.stringify({ 'conv-1': 'чужой недописанный текст' }))
  loginAs('petrov')

  assert.equal(drafts.draftFor('conv-1'), '', 'старая карта не должна подставляться новому владельцу')
  assert.equal(localStorage.getItem('gb_msg_drafts'), null, 'старая карта должна быть стёрта, а не оставлена лежать')
})

test('без входа черновик некуда писать и неоткуда читать', () => {
  localStorage.clear()
  loginAs('')
  drafts.saveDraft('conv-1', 'текст до входа')
  assert.equal(drafts.draftFor('conv-1'), '')
  assert.deepEqual(Object.keys(localStorage).filter((k) => k.startsWith('gb.drafts.')), [])
})

test('пустой текст удаляет запись, а не хранит пустую строку', () => {
  localStorage.clear()
  loginAs('ivanov')
  drafts.saveDraft('conv-1', 'черновик')
  drafts.saveDraft('conv-1', '   ')          //пробелы — это тоже «пусто»
  assert.equal(drafts.draftFor('conv-1'), '')
  //Последняя запись ушла — карту не держим вовсе.
  assert.deepEqual(Object.keys(localStorage).filter((k) => k.startsWith('gb.drafts.')), [])
})

test('clearDraft стирает черновик только своей беседы', () => {
  localStorage.clear()
  loginAs('ivanov')
  drafts.saveDraft('conv-1', 'первый')
  drafts.saveDraft('conv-2', 'второй')
  drafts.clearDraft('conv-1')
  assert.equal(drafts.draftFor('conv-1'), '')
  assert.equal(drafts.draftFor('conv-2'), 'второй')
})
