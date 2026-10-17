// serverSwitch.test.mjs — смена сервера не уносит чужое (аудит 17.10.2026).
//
// ━━ ЧТО БЫЛО ━━
// Экран «⚙ Сервер» сохранял новый адрес и оставлял токены прежней сессии. Следующий
// запрос уходил на НОВЫЙ сервер с `Authorization` прежнего, а страж роутера, видя
// «вошедшего», отправлял прямо в кабинет. Очередь неотправленных оценок ключевалась одним
// логином: войди тем же логином на другом сервере — и оценки первого уехали бы туда.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать суффикс сервера из владельца очереди — краснеет
// второй тест; вернуть `setApiBase` в экран подключения — краснеет четвёртый.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

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

const server = await import('../src/api/server.js')
const outbox = await import('../src/api/outbox.js')
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

function loginAs(login) {
  localStorage.setItem('gb.user', JSON.stringify({ login, role: 'teacher' }))
  outbox.reloadOutbox()
}

const cell = (grade) => ({ surname: 'Иванов', name: 'Иван', lesson_id: 'les-1', grade })

test('«свой» сервер — без суффикса, чужой — со своим адресом', () => {
  server.clearApiBase()
  assert.equal(server.serverScope(), '')
  server.setApiBase(server.DEFAULT_API_BASE)
  assert.equal(server.serverScope(), '', 'вшитый боевой адрес — тот же «свой» сервер')
  server.setApiBase('other.example/')
  assert.equal(server.serverScope(), 'https://other.example')
  server.clearApiBase()
})

test('очередь неотправленного остаётся за своим сервером', () => {
  server.clearApiBase()
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell('5'))
  assert.ok(localStorage.getItem('gb.outbox.teach1'), 'ключ «своего» сервера не сменился')

  server.setApiBase('https://other.example')
  outbox.reloadOutbox()
  assert.equal(outbox.pending.value.length, 0, 'оценка первого сервера уехала бы на второй')
  outbox.enqueueGrade(cell('4'))
  assert.ok(localStorage.getItem('gb.outbox.teach1@https://other.example'))

  server.clearApiBase()
  outbox.reloadOutbox()
  assert.deepEqual(outbox.pending.value.map((e) => e.payload.grade), ['5'])
  outbox.clearOutbox()
})

test('switchServer гасит сессию ДО смены адреса и только при настоящей смене', async () => {
  server.clearApiBase()
  const seen = []
  await server.switchServer('https://other.example', () => { seen.push(server.getApiBase()) })
  assert.deepEqual(seen, [''], 'выход обязан идти на ТОТ сервер, что выдал токен')
  assert.equal(server.getApiBase(), 'https://other.example')

  await server.switchServer('other.example', () => { seen.push('лишний выход') })
  assert.deepEqual(seen, [''], 'тот же адрес — не смена сервера')

  //Выход упал (нет сети) — адрес всё равно меняется: локальная часть выхода сделана.
  await server.switchServer('https://third.example', () => { throw new Error('офлайн') })
  assert.equal(server.getApiBase(), 'https://third.example')
  server.clearApiBase()
})

test('экран подключения меняет сервер только через switchServer с выходом', () => {
  const src = readFileSync(join(ROOT, 'src/pages/ConnectServer.vue'), 'utf8')
  assert.doesNotMatch(src, /\bsetApiBase\s*\(/, 'адрес снова сохраняется мимо выхода из сессии')
  assert.match(src, /switchServer\(\s*u\s*,\s*endSession\s*\)/)
  assert.match(src, /const endSession = \(\) => auth\.logout\(\)/)
})
