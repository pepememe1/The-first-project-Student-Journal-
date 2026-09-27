// outboxBaseAndDurable.test.mjs — очередь телефона не затирает чужую правку молча и не
// теряет работу, когда ОС чистит localStorage (исследование синка W-13б, W-13в).
//
// ━━ ЧТО БЫЛО ━━
// W-13б: оценка без сети уходила БЕЗ версии, и сервер принимал её поверх всего, что
// появилось за это время, — ранняя правка с телефона молча затирала позднюю, в том числе
// исправление самого преподавателя с ПК. Теперь она едет с номером клетки, который человек
// видел, конфликт (409) уходит в «не принято» с выбором «своё / серверное».
// W-13в: очередь жила только в localStorage, а его в приложении ОС вправе освободить.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: не передавать `base_seq` — краснеет «уходит с базой»;
// переписывать базу при повторной правке — краснеет «база — до первой правки»; не
// отличать 409-конфликт — краснеет «конфликт с выбором»; не зеркалировать — краснеет
// «очередь переживает очистку localStorage».
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
  outbox.setDurableStore(null)
  outbox.reloadOutbox()
  outbox.clearOutbox()
  outbox.setSender(null)
}

afterEach(() => {
  outbox.setSender(null)
  outbox.setDurableStore(null)
  outbox._retryState(true)
})

const cell = { surname: 'Петров', name: 'Пётр', lesson_id: 'les-1', student_id: 'stud:petrov' }

test('оценка без сети уходит с номером клетки, который человек видел', async () => {
  fresh()
  outbox.enqueueGrade({ ...cell, grade: '4', base_seq: 17 })
  const sent = []
  outbox.setSender(async (e) => { sent.push(e.payload); return { data: { ok: true } } })
  await outbox.flushOutbox()
  assert.equal(sent[0].base_seq, 17, 'правка ушла без базы — сервер затёр бы чужую')
})

test('база — до ПЕРВОЙ правки: повторная правка той же клетки её не переписывает', () => {
  fresh()
  outbox.enqueueGrade({ ...cell, grade: '4', base_seq: 17 })
  outbox.enqueueGrade({ ...cell, grade: '5', base_seq: 99 })
  const [e] = outbox.pending.value
  assert.equal(e.payload.grade, '5')
  assert.equal(e.payload.base_seq, 17)
})

test('конфликт — в «не принято» с серверным значением и выбором', async () => {
  fresh()
  outbox.enqueueGrade({ ...cell, grade: '4', base_seq: 17 })
  outbox.setSender(async () => {
    const err = new Error('409')
    err.response = { status: 409, data: { detail: { code: 'conflict', message: 'изменили',
      server: { grade: '3' } } } }
    throw err
  })
  await outbox.flushOutbox()
  const [r] = outbox.rejected.value
  assert.deepEqual(r.conflict, { server: { grade: '3' } })
  //«Оставить моё» — та же правка без сверки базы.
  const sent = []
  outbox.setSender(async (e) => { sent.push(e.payload); return { data: { ok: true } } })
  outbox.resolveConflict(r.key, true)
  assert.equal(outbox.rejected.value.length, 0)
  await outbox.flushOutbox()
  assert.equal(sent[0].grade, '4')
  assert.ok(!('base_seq' in sent[0]), '«оставить моё» снова сверялось с базой и снова получило бы 409')
})

test('«оставить серверное» — запись уходит и больше не отправляется', async () => {
  fresh()
  outbox.enqueueGrade({ ...cell, grade: '4', base_seq: 17 })
  outbox.setSender(async () => {
    const err = new Error('409')
    err.response = { status: 409, data: { detail: { code: 'conflict', server: { grade: '3' } } } }
    throw err
  })
  await outbox.flushOutbox()
  const [r] = outbox.rejected.value
  outbox.resolveConflict(r.key, false)
  assert.equal(outbox.rejected.value.length, 0)
  assert.equal(outbox.pending.value.length, 0, '«оставить серверное» снова поставило правку в очередь')
})

test('очередь переживает очистку localStorage — из надёжного зеркала', async () => {
  fresh()
  const box = new Map()
  outbox.setDurableStore({ get: async (k) => box.get(k) ?? null, set: async (k, v) => { box.set(k, v) } })
  outbox.enqueueGrade({ ...cell, grade: '5', base_seq: 3 })
  await new Promise((r) => setTimeout(r, 0))
  //ОС освободила хранилище приложения.
  localStorage.removeItem('gb.outbox.teach1')
  outbox.reloadOutbox()
  assert.equal(outbox.pending.value.length, 0, 'предпосылка: локальная копия пропала')
  assert.equal(await outbox.restoreFromDurable(), true)
  assert.equal(outbox.pendingGrade('les-1', 'Петров', 'Пётр', 'stud:petrov'), '5',
    'неотправленная оценка пропала вместе с localStorage')
})

test('живая локальная копия главнее зеркала', async () => {
  fresh()
  const box = new Map([['gb.outbox.teach1', JSON.stringify([{ kind: 'grade', key: 'old',
    payload: { grade: '2' }, seq: 1 }])]])
  outbox.setDurableStore({ get: async (k) => box.get(k) ?? null, set: async () => {} })
  outbox.enqueueGrade({ ...cell, grade: '5' })
  assert.equal(await outbox.restoreFromDurable(), false)
  assert.equal(outbox.pending.value.length, 1)
})

test('отказ по существу через «оставить моё» не переотправляется', async () => {
  fresh()
  outbox.enqueueGrade({ ...cell, grade: '4', base_seq: 17 })
  outbox.setSender(async () => {
    const err = new Error('404')
    err.response = { status: 404, data: { detail: 'Занятие не найдено' } }
    throw err
  })
  await outbox.flushOutbox()
  const [r] = outbox.rejected.value
  assert.ok(r && !r.conflict)
  assert.equal(outbox.resolveConflict(r.key, true), false)
  assert.equal(outbox.pending.value.length, 0, 'отказ по существу переотправлен — он получит тот же отказ')
  assert.equal(outbox.rejected.value.length, 1)
})

test('журнал ставит оценку в очередь с номером клетки (у базы есть вызывающий)', async () => {
  const { readFileSync } = await import('node:fs')
  const src = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
  const call = src.slice(src.indexOf('enqueueGrade({ surname: s.surname'))
  assert.match(call.slice(0, 300), /base_seq: s\.seqs \? s\.seqs\[key\] : undefined/,
    'журнал ставит оценку в очередь без номера клетки — сервер снова затирал бы чужое')
})
