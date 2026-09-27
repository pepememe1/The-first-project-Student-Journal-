// unsentWork.test.mjs — выход из аккаунта спрашивает про неотправленное (W-11, 26.09.2026).
//
// ━━ ЧТО БЫЛО ━━
// `desk_outbox.has_unsent` существовала и не звалась никем; выход спрашивал «точно?»
// только у пасхалки. Преподаватель уходил с общего компьютера, уверенный, что оценки на
// сервере, а они ждали его там же: уйдут, только когда он снова войдёт ЗДЕСЬ.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать вызов проверки из `onLogout` — краснеет проводка;
// перестать считать признак программы `unsent` — краснеет «признак программы главнее»;
// принимать страницу-заглушку сайта за ответ программы — краснеет «сайт — не программа».
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
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size },
  }
}
globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage }

const outbox = await import('../src/api/outbox.js')
const W = await import('../src/utils/unsentWork.js')

function fresh() {
  localStorage.setItem('gb.user', JSON.stringify({ login: 'teach1', role: 'teacher' }))
  outbox.reloadOutbox()
  outbox.clearOutbox()
  outbox.setSender(null)
}

afterEach(() => {
  outbox.setSender(null)
  outbox._retryState(true)
})

const notProgram = async () => ({ status: 404, ok: false, json: async () => ({}) })

test('пусто везде — выход без вопроса', () => {
  const s = W.unsentSummary(null, 0, 0)
  assert.equal(W.shouldAskBeforeLogout(s), false)
})

test('очередь сайта и программы складываются', () => {
  const s = W.unsentSummary({ outbox: { pending: 1, conflicts: 2, rejected: 1 } }, 3, 1)
  assert.deepEqual([s.waiting, s.problems, s.total], [4, 4, 8])
  assert.equal(W.shouldAskBeforeLogout(s), true)
  assert.deepEqual(W.unsentMessageParts(s).map(([k]) => k),
    ['logout.unsent.waiting', 'logout.unsent.problems'])
})

test('признак программы главнее счётчиков', () => {
  const s = W.unsentSummary({ unsent: true, outbox: { pending: 0 } }, 0, 0)
  assert.equal(W.shouldAskBeforeLogout(s), true,
    'программа сказала «есть неотправленное», а выход ушёл молча')
})

test('очередь программы не прочиталась — «не знаем», а не «всё ушло»', () => {
  const s = W.unsentSummary({ outbox: { available: false } }, 0, 0)
  assert.equal(s.unknown, true)
  assert.equal(W.shouldAskBeforeLogout(s), true)
})

test('сайт — не программа: 404 и страница-заглушка с кодом 200', async () => {
  assert.equal(await W.readDeskStatus(notProgram), null)
  const spaPage = async () => ({ status: 200, ok: true,
    json: async () => { throw new SyntaxError('Unexpected token <') } })
  assert.equal(await W.readDeskStatus(spaPage), null,
    'страницу SPA приняли за ответ программы')
})

test('беда своего локального сервера — «не знаем»', async () => {
  const broken = async () => ({ status: 500, ok: false, json: async () => ({ detail: 'x' }) })
  assert.deepEqual(await W.readDeskStatus(broken), { unknown: true })
})

test('очередь сайта сначала досылается, и дошедшее не спрашивается', async () => {
  fresh()
  outbox.enqueueGrade({ surname: 'Петров', name: 'Пётр', lesson_id: 'les-1', grade: '5',
    student_id: 'stud:petrov' })
  const s = await W.collectUnsent({ fetchImpl: notProgram,
    flush: async () => outbox.clearOutbox() })
  assert.equal(W.shouldAskBeforeLogout(s), false, 'спросили о том, что уже ушло')
})

test('без сети досылка не держит кнопку выхода дольше отведённого', async () => {
  fresh()
  outbox.enqueueGrade({ surname: 'Петров', name: 'Пётр', lesson_id: 'les-1', grade: '5',
    student_id: 'stud:petrov' })
  const t0 = Date.now()
  const s = await W.collectUnsent({ fetchImpl: notProgram,
    flush: () => new Promise(() => {}), waitMs: 50 })
  assert.ok(Date.now() - t0 < 2000, 'выход завис на досылке')
  assert.equal(s.waiting, 1)
  assert.equal(W.shouldAskBeforeLogout(s), true)
})

test('проводка: выход спрашивает ДО auth.logout()', () => {
  const src = readFileSync(new URL('../src/pages/Settings.vue', import.meta.url), 'utf8')
  const body = src.slice(src.indexOf('async function onLogout()'))
  const ask = body.indexOf('unsentAllowsLogout()')
  const out = body.indexOf('auth.logout()')
  assert.ok(ask > 0 && out > 0, 'проверка неотправленного не вызывается при выходе')
  assert.ok(ask < out, 'вопрос задаётся уже после выхода — отступать некуда')
})

//Свой срок у теста: вернись дефект — прогон покраснеет, а не повиснет навсегда.
test('зависший локальный сервер не держит выход: «не знаем» по сроку', { timeout: 3000 }, async () => {
  const t0 = Date.now()
  const hung = () => new Promise(() => {})
  assert.deepEqual(await W.readDeskStatus(hung, 50), { unknown: true })
  assert.ok(Date.now() - t0 < 2000, 'выход завис на опросе программы')
})
