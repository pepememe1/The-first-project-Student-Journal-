// clientReport.test.mjs — ошибки интерфейса и время старта уходят на сервер без ПДн
// (23.10.2026). Консоль на телефоне студента не видит никто, поэтому отчёт; а раз ручка
// открыта до входа, в отчёт не должно попасть ничего о человеке.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const { scrubMessage, topFrame, routeTemplate, isNoise, makeReporter, MAX_ERRORS, reportOrigin } =
  await import('../src/utils/clientReport.js')

test('чистка сообщения: тот же набор, что в server/tests/test_client_metrics.py', () => {
  assert.equal(scrubMessage("reading 'Иванов'"), 'reading …')
  assert.equal(scrubMessage('x «Петров» y'), 'x … y')
  assert.equal(scrubMessage('mail a@b.ru now'), 'mail … now')
  assert.equal(scrubMessage('id 12345 at 7'), 'id N at 7')
  const cut = 'x'.repeat(150) + " 'Иванов Пётр " + 'y'.repeat(800) + "'"
  assert.ok(!scrubMessage(cut).includes('Иванов'), 'оборванная обрезкой кавычка пропустила имя')
  assert.equal(scrubMessage("Can't find variable: foo"), "Can't find variable: foo")
  assert.equal(scrubMessage("Can't read 'Иванов'"), "Can't read …")
})

test('кадр стека — только файл бандла, без адреса сайта', () => {
  const stack = 'TypeError: x\n    at f (https://esstu-gradebook.ru/assets/index-Ab1.js:1:2345)\n' +
    '    at g (https://esstu-gradebook.ru/assets/other.js:3:4)'
  assert.equal(topFrame(stack), 'assets/index-Ab1.js:1:2345')
  assert.equal(topFrame('нет стека'), '')
})

test('маршрут — шаблон, а не адрес со значениями', () => {
  const route = { fullPath: '/teacher/messages?peer=ivanov',
                  matched: [{ path: '/teacher' }, { path: '/teacher/messages' }] }
  assert.equal(routeTemplate(route), '/teacher/messages')
  assert.equal(routeTemplate({ matched: [] }), '/')
})

test('сеть, отменённый запрос и старый чанк — не дефект кода', () => {
  assert.equal(isNoise({ name: 'AxiosError', message: 'Network Error' }), true)
  assert.equal(isNoise({ isAxiosError: true }), true)
  assert.equal(isNoise(new Error('Failed to fetch dynamically imported module: /assets/x.js')), true)
  assert.equal(isNoise(new Error('ResizeObserver loop completed with undelivered notifications')), true)
  assert.equal(isNoise(new TypeError("Cannot read properties of undefined (reading 'a')")), false)
})

test('одна и та же ошибка уходит один раз, всего — не больше потолка', () => {
  const sent = []
  const r = makeReporter({ send: (p) => sent.push(p), platform: 'android', version: '1' })
  const route = { matched: [{ path: '/student' }] }
  r.error(new TypeError('boom'), route)
  r.error(new TypeError('boom'), route)
  assert.equal(sent.length, 1)
  for (let i = 0; i < 50; i++) r.error(new Error(`ошибка ${String.fromCharCode(1072 + i % 32)}`), route)
  assert.equal(sent.length, MAX_ERRORS)
  const e = sent[0].errors[0]
  assert.deepEqual(Object.keys(e).sort(), ['frame', 'message', 'name', 'route'])
  assert.equal(sent[0].platform, 'android')
})

test('время старта уходит один раз за запуск', () => {
  const sent = []
  const r = makeReporter({ send: (p) => sent.push(p), platform: 'web', version: '1' })
  r.startup(812.6, { matched: [{ path: '/login' }] }, { mem: 4, cores: 8 })
  r.startup(900, { matched: [] })
  assert.equal(sent.length, 1)
  assert.deepEqual(sent[0].startup, { ms: 813, route: '/login', mem: 4, cores: 8 })
})

test('приложение подключает отчёты на старте', () => {
  //Отчётчик без вызова — то же, что его отсутствие: ошибки снова уходили бы только в консоль.
  const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8')
  assert.match(main, /installClientReport\(app, router,/)
})

test('адрес отчёта: стенд в браузере шлёт к себе, программа и телефон — на публичный сайт', () => {
  const pub = 'https://esstu-gradebook.ru'
  // Живой прогон 27.10.2026: стенд на 127.0.0.1 слал отчёты на бой и получал 405.
  assert.equal(reportOrigin({ desktop: false, native: false, here: 'http://127.0.0.1:8765', publicOrigin: pub }),
    'http://127.0.0.1:8765')
  assert.equal(reportOrigin({ desktop: false, native: false, here: pub, publicOrigin: pub }), pub)
  // Программа: страница с 127.0.0.1, но отчёт идёт мимо локального сервера (§4.50).
  assert.equal(reportOrigin({ desktop: true, native: false, here: 'http://127.0.0.1:51234', publicOrigin: pub }), pub)
  assert.equal(reportOrigin({ desktop: false, native: true, here: 'https://localhost', publicOrigin: pub }), pub)
})
