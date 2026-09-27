// outboxRetryPolicy.test.mjs — очередь сайта не теряет временные сбои и не плодит
// дубли занятий (аудит 22.09.2026, находки F-05 и F-06).
//
// ━━ ЧТО БЫЛО ━━
// • F-06: любой 4xx считался отказом по существу — 408 (таймаут) и 429 (ограничитель)
//   выбрасывали оценку в «отклонённые» навсегда; а повтор после 503 ждал только
//   перехода «офлайн → онлайн», которого при живой сети не бывает, — очередь лежала
//   часами.
// • F-05: создание занятия, чей ответ потерялся в сети, при повторе заводило ВТОРОЕ
//   занятие: id выдавал сервер на каждый вызов.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `TRANSIENT_4XX` из условия отказа — краснеет
// «429 и 408 — временный сбой»; убрать `body.id = uid` в `lessonCreateBody` — краснеет «тело создания занятия».
import { test, afterEach } from 'node:test'
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
  }
}

globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage }

const outbox = await import('../src/api/outbox.js')

function fresh() {
  localStorage.setItem('gb.user', JSON.stringify({ login: 'teach1', role: 'teacher' }))
  outbox.reloadOutbox()
  outbox.clearOutbox()
  outbox._retryState(true)
}

function failWith(status) {
  return async () => {
    const err = new Error(`HTTP ${status}`)
    err.response = { status, data: { detail: `ответ ${status}` } }
    throw err
  }
}

afterEach(() => {
  outbox.setSender(null)
  outbox._retryState(true)
})

const cell = { surname: 'Петров', name: 'Пётр', lesson_id: 'les-1', grade: '5' }

for (const status of [408, 425, 429, 500, 503]) {
  test(`${status} — временный сбой: запись ждёт, повтор поставлен по таймеру`, async () => {
    fresh()
    outbox.enqueueGrade(cell)
    outbox.setSender(failWith(status))
    const res = await outbox.flushOutbox()
    assert.equal(res.rejected, 0, `${status} выбросил оценку в «отклонённые»`)
    assert.equal(outbox.pending.value.length, 1, 'временный сбой потерял запись')
    assert.equal(outbox._retryState().scheduled, true,
      'повтор не поставлен — очередь лежала бы до перехода офлайн→онлайн')
  })
}

test('422 — отказ по существу, как и раньше: запись уходит в отклонённые', async () => {
  fresh()
  outbox.enqueueGrade(cell)
  outbox.setSender(failWith(422))
  const res = await outbox.flushOutbox()
  assert.equal(res.rejected, 1)
  assert.equal(outbox.pending.value.length, 0)
  assert.equal(outbox._retryState().scheduled, false, 'отказ по существу повторять незачем')
})

test('повтор создания занятия уходит с ТЕМ ЖЕ id, что и первая попытка онлайн', async () => {
  fresh()
  const id = outbox.newLessonId()
  assert.match(id, /^[0-9a-f-]{36}$/)
  const tempId = outbox.enqueueLessonCreate({ group: 'К-24', subject: 'Математика',
    type: 'Практика', id: 'чужой-id-не-должен-пройти' }, id)
  assert.equal(outbox.uuidFromTempId(tempId), id)

  const sent = []
  outbox.setSender(async (entry) => {
    sent.push(entry)
    const err = new Error('сеть')        // ответ «потерялся» — связи нет
    throw err
  })
  await outbox.flushOutbox()
  await outbox.flushOutbox()
  outbox.setSender(null)
  assert.ok(sent.length >= 1)
  for (const e of sent) {
    assert.equal(outbox.uuidFromTempId(e.payload.__tempId), id,
      'повтор создания получил бы новый id — сервер завёл бы второе занятие')
  }
})

test('тело создания занятия несёт id из временного — один на все повторы', () => {
  const id = outbox.newLessonId()
  const body = outbox.lessonCreateBody({ group: 'К-24', type: 'Практика', __tempId: `tmp:${id}` })
  assert.equal(body.id, id, 'повтор ушёл бы без id — сервер завёл бы второе занятие')
  assert.equal(body.__tempId, undefined, 'служебное поле очереди уехало на сервер')
  const legacy = outbox.lessonCreateBody({ group: 'К-24', __tempId: 'tmp:1712345678-0.5' })
  assert.equal(legacy.id, undefined, 'не-UUID временный id не годится серверу в id')
})

test('временный id без UUID (старая очередь) — id не шлём, его выдаст сервер', () => {
  assert.equal(outbox.uuidFromTempId('tmp:1712345678-0.123'), '')
  assert.equal(outbox.uuidFromTempId('not-a-temp'), '')
})

test('успешная выгрузка сбрасывает нарастание паузы', async () => {
  fresh()
  outbox.enqueueGrade(cell)
  outbox.setSender(failWith(503))
  await outbox.flushOutbox()
  assert.ok(outbox._retryState().attempt >= 1, 'после сбоя пауза обязана начать расти')
  //Сеть ожила раньше таймера — выгрузка прошла сама; счётчик паузы обязан обнулиться,
  //иначе следующий сбой ждал бы уже минуты, а не секунды.
  outbox.setSender(async () => ({ data: { ok: true } }))
  await outbox.flushOutbox()
  assert.equal(outbox.pending.value.length, 0)
  assert.equal(outbox._retryState().attempt, 0)
})
