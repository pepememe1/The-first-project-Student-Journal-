// outboxTermPeriod.test.mjs — офлайн-операция помнит СВОЙ учебный период (находка
// ревью J10, 18.09.2026; починено 20.09.2026).
//
// ━━ ЧТО БЫЛО ━━
// Итоговая оценка уезжала без периода, а сервер штампует её `current_term` в момент
// ИСПОЛНЕНИЯ. Между нажатием и доставкой у очереди лежат каникулы: закрыл первый
// семестр 30 декабря без сети — 12 января оценка легла во второй и заперла его.
// Второе следствие — ключ схлопывания: без периода декабрьская ведомость и январская
// считались ОДНОЙ записью, и первая исчезала молча.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть ключ без периода — краснеет второй тест; убрать
// year/semester из полезной нагрузки — первый.
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
  }
}
globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage }

const outbox = await import('../src/api/outbox.js')

localStorage.setItem('gb.user', JSON.stringify({ login: 'teacher1', role: 'teacher' }))
outbox.reloadOutbox()

const row = (over = {}) => ({
  group: 'К-51', subject: 'История', surname: 'Батоев', name: 'Баир', grade: '5',
  form: 'Экзамен', year: '2026/2027', semester: 1, ...over,
})

test('период уезжает вместе с итоговой', () => {
  outbox.clearOutbox()
  outbox.enqueueTermGrade(row())
  const e = outbox.pending.value[0]
  assert.equal(e.payload.year, '2026/2027',
    'сервер запишет итоговую в тот период, который идёт в день доставки, а не в тот, где её ставили')
  assert.equal(e.payload.semester, 1)
})

test('ведомости за разные семестры не схлопываются в одну запись', () => {
  outbox.clearOutbox()
  outbox.enqueueTermGrade(row({ grade: '4', semester: 1 }))
  outbox.enqueueTermGrade(row({ grade: '5', semester: 2 }))
  assert.equal(outbox.pending.value.length, 2,
    'итоговая за первый семестр заместилась итоговой за второй — работа пропала молча')
  assert.deepEqual(outbox.pending.value.map((e) => e.payload.semester).sort(), [1, 2])
})

test('повтор в ТОМ ЖЕ периоде по-прежнему схлопывается', () => {
  //Обратная сторона: правка одной и той же оценки не должна плодить записи — сервер
  //применил бы их по очереди, а при обрыве оставил бы не то, что человек видел.
  outbox.clearOutbox()
  outbox.enqueueTermGrade(row({ grade: '3' }))
  outbox.enqueueTermGrade(row({ grade: '5' }))
  assert.equal(outbox.pending.value.length, 1)
  assert.equal(outbox.pending.value[0].payload.grade, '5')
})

test('запись без периода ставится в очередь по-прежнему', () => {
  //Старые записи в localStorage и клиенты без термина обязаны доезжать как раньше.
  outbox.clearOutbox()
  const { year, semester, ...noTerm } = row()
  void year; void semester
  outbox.enqueueTermGrade(noTerm)
  assert.equal(outbox.pending.value.length, 1)
  assert.equal(outbox.pending.value[0].key, 'term|К-51|История|Батоев|Баир')
})
