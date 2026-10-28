// sharedRequest.test.mjs — одновременные одинаковые GET делят один запрос (28.10.2026).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { makeShared } from '../src/api/sharedRequest.js'
import { readSource } from './_readSource.mjs'

//client.js в Node не грузится (axios, окно), поэтому подключение проверяем текстом: без
//поколения сессии в ключе общий запрос отдал бы ответ прежнего владельца новому (§4.23).
test('sharedGet ключуется поколением сессии, настройки идут через него', () => {
  assert.match(readSource('api/client.js'), /export const sharedGet = makeShared\(\(url\) => api\.get\(url\), \(\) => sessionGen\)/)
  assert.match(readSource('api/endpoints.js'), /getPrefs: \(\) => sharedGet\('\/me\/prefs'\)/)
})

function fakeServer() {
  const calls = []
  const fetch = (url) => new Promise((resolve, reject) => calls.push({ url, resolve, reject }))
  return { calls, fetch }
}

test('одновременные вызовы — один запрос, у каждого своя копия данных', async () => {
  const s = fakeServer()
  const get = makeShared(s.fetch, () => 1)
  const a = get('/me/prefs')
  const b = get('/me/prefs')
  assert.equal(s.calls.length, 1)
  s.calls[0].resolve({ status: 200, data: { theme: 'dark' } })
  const [ra, rb] = await Promise.all([a, b])
  ra.data.theme = 'light'
  assert.equal(rb.data.theme, 'dark', 'правка одного стора не должна попасть в другой')
})

test('готовый ответ не хранится: следующий вызов идёт на сервер', async () => {
  const s = fakeServer()
  const get = makeShared(s.fetch, () => 1)
  const first = get('/me/prefs')
  s.calls[0].resolve({ data: {} })
  await first
  get('/me/prefs')
  assert.equal(s.calls.length, 2)
})

test('запрос прежней сессии новому владельцу не достаётся (§4.23)', () => {
  const s = fakeServer()
  let gen = 1
  const get = makeShared(s.fetch, () => gen)
  get('/me/prefs')
  gen = 2
  get('/me/prefs')
  assert.equal(s.calls.length, 2)
})

test('отказ получают все ждавшие, а следующий вызов пробует снова', async () => {
  const s = fakeServer()
  const get = makeShared(s.fetch, () => 1)
  const a = get('/me/prefs')
  const b = get('/me/prefs')
  s.calls[0].reject(new Error('нет сети'))
  await assert.rejects(a)
  await assert.rejects(b)
  get('/me/prefs')
  assert.equal(s.calls.length, 2)
})
