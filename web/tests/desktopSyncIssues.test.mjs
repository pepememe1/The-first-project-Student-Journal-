// desktopSyncIssues.test.mjs — значок синка программы говорит обо ВСЕХ бедах, а не о
// трёх из шести (аудит 22.09.2026, находка F-08).
//
// 🔥 Что было: `issuesOf` учитывал вход, конфликты и отказы, но молчал о двух бедах,
// после которых человек видит неправду на экране:
//   • `mirror_error` — копия, из которой рисуется журнал, не обновилась (устаревшие оценки);
//   • ждущие правки при нет связи — «ваши оценки ещё не ушли» не звучало нигде.
// И конфликты считались по старой базе, где «конфликтом» была любая свежая серверная
// оценка; теперь они приходят из очереди правок программы (`outbox`).
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать ветку `mirror_error` — краснеет «копия не обновилась»;
// убрать условие `stuck` — краснеет «при живой связи ждущие правки не шумят».
import { test } from 'node:test'
import assert from 'node:assert/strict'

globalThis.document = {
  hidden: false,
  createElement: () => ({ innerHTML: '', content: {}, firstChild: null }),
  addEventListener: () => {}, removeEventListener: () => {},
}
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }

const { issuesOf } = await import('../src/api/desktopSync.js')
const kinds = (st) => issuesOf(st).map((i) => i.kind)

const quiet = { available: true, online: true, error: '', auth_error: '', mirror_error: '',
  mirror_ok_at: '2026-09-25T10:00:00Z', outbox_stopped: '',
  outbox: { available: true, pending: 0, conflicts: 0, rejected: 0 } }

test('всё хорошо — значок молчит', () => {
  assert.deepEqual(kinds(quiet), [])
})

test('копия не обновилась — это видно, со временем последнего успеха', () => {
  const got = issuesOf({ ...quiet, mirror_error: 'нет активной сессии с сервером' })
  assert.deepEqual(got.map((i) => i.kind), ['mirror'])
  assert.equal(got[0].since, '2026-09-25T10:00:00Z')
})

test('правки ждут, а связи нет — это видно', () => {
  const st = { ...quiet, online: false, error: 'ConnectTimeout',
    outbox: { ...quiet.outbox, pending: 3 } }
  assert.deepEqual(kinds(st), ['pending'])
  assert.equal(issuesOf(st)[0].count, 3)
})

test('при живой связи ждущие правки не шумят (очередь пустеет через секунду)', () => {
  assert.deepEqual(kinds({ ...quiet, outbox: { ...quiet.outbox, pending: 2 } }), [])
})

test('конфликты и отказы — из очереди программы', () => {
  const st = { ...quiet, outbox: { ...quiet.outbox, conflicts: 1, rejected: 2 } }
  assert.deepEqual(kinds(st), ['conflicts', 'rejected'])
})

test('синк не запущен, но очередь известна — о ней всё равно говорим', () => {
  const st = { available: false, outbox: { available: true, pending: 0, conflicts: 1, rejected: 0 } }
  assert.deepEqual(kinds(st), ['conflicts'])
})

test('на сайте (нет ни синка, ни очереди) — молчим', () => {
  assert.deepEqual(kinds({ available: false }), [])
  assert.deepEqual(kinds(null), [])
})

// «Сверщик» (26.09.2026): расхождение копии — беда, успешная сверка — тихое «сверено».
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать ветку `verify` в `issuesOf` — краснеет первый тест;
// убрать проверку возраста в `verifiedAt` — краснеет «вчерашняя сверка не считается».
const { verifiedAt } = await import('../src/api/desktopSync.js')

test('Сверщик нашёл расхождение — это беда на значке', () => {
  const st = { ...quiet, verify: { ok: false, at: '2026-09-26T10:00:00Z',
    mismatch: [{ table: 'grades', server: 3, local: 4 }] } }
  assert.deepEqual(kinds(st), ['verify'])
})

test('свежая успешная сверка даёт «сверено», вчерашняя — нет', () => {
  const now = Date.parse('2026-09-26T12:00:00Z')
  const fresh = { ...quiet, verify: { ok: true, at: '2026-09-26T11:30:00Z', mismatch: [] } }
  assert.equal(verifiedAt(fresh, now), '2026-09-26T11:30:00Z')
  const stale = { ...quiet, verify: { ok: true, at: '2026-09-25T11:30:00Z', mismatch: [] } }
  assert.equal(verifiedAt(stale, now), '', 'вчерашняя сверка выдана за сегодняшнюю')
  assert.equal(verifiedAt({ ...quiet, verify: { ok: false, at: fresh.verify.at } }, now), '')
  assert.equal(verifiedAt(null, now), '')
})
