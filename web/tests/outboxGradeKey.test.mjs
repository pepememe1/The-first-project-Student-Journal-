// outboxGradeKey.test.mjs — у оценки в очереди телефона ОДИН ключ на все места
// (исследование синка 25.09.2026, находка W-13а).
//
// ━━ ЧТО БЫЛО ━━
// Постановка ключевала оценку по `student_id` (J08), поиск ждущей оценки — по ФИО,
// перепривязка к настоящему id занятия — снова по ФИО. Поиск не находил НИ ОДНОЙ
// современной записи: пунктир «не отправлено» не рисовался, а средний балл без сети не
// учитывал выставленное — ровно то, ради чего он заведён. А перепривязка давала клетке
// второй ключ, и следующая правка той же клетки вставала в очередь рядом, а не вместо.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть поиск по ключу «ФИО» — краснеют «ждущая оценка видна»
// и «у тёзок своя»; вернуть ключ перепривязки по ФИО — краснеет «одна клетка — одна запись».
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
  outbox.setSender(null)
}

//Сетевая ошибка честно ставит повтор по таймеру (F-06); тест его снимает, иначе живой
//таймер держал бы процесс node вечно.
afterEach(() => {
  outbox.setSender(null)
  outbox._retryState(true)
})

test('ждущая оценка с id студента видна журналу', () => {
  fresh()
  outbox.enqueueGrade({ surname: 'Петров', name: 'Пётр', lesson_id: 'les-1', grade: '5',
    student_id: 'stud:petrov' })
  assert.equal(outbox.pendingGrade('les-1', 'Петров', 'Пётр', 'stud:petrov'), '5',
    'пунктир «не отправлено» и средний балл без сети не увидели бы выставленное')
})

test('у полных тёзок у каждого своя ждущая оценка', () => {
  fresh()
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Иван', lesson_id: 'les-1', grade: '5',
    student_id: 'stud:ivanov1' })
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Иван', lesson_id: 'les-1', grade: '2',
    student_id: 'stud:ivanov2' })
  assert.equal(outbox.pending.value.length, 2, 'оценки тёзок схлопнулись в одну')
  assert.equal(outbox.pendingGrade('les-1', 'Иванов', 'Иван', 'stud:ivanov1'), '5')
  assert.equal(outbox.pendingGrade('les-1', 'Иванов', 'Иван', 'stud:ivanov2'), '2')
})

test('запись прежней сборки (без id студента) тоже видна', () => {
  fresh()
  outbox.enqueueGrade({ surname: 'Сидоров', name: 'Семён', lesson_id: 'les-1', grade: '4' })
  assert.equal(outbox.pendingGrade('les-1', 'Сидоров', 'Семён', 'stud:sidorov'), '4')
})

test('одна клетка — одна запись и после перепривязки к настоящему занятию', async () => {
  fresh()
  const tmp = outbox.enqueueLessonCreate({ group: 'К74/1', subject: 'Физика', type: 'ДЗ' })
  outbox.enqueueGrade({ surname: 'Петров', name: 'Пётр', lesson_id: tmp, grade: '4',
    student_id: 'stud:petrov' })
  outbox.setSender(async (e) => {
    if (e.kind === 'lesson.create') return { data: { id: 'real-9' } }
    throw new Error('network down')            //оценка не доехала
  })
  await outbox.flushOutbox()
  //Преподаватель поправил ту же клетку уже на настоящем занятии.
  outbox.enqueueGrade({ surname: 'Петров', name: 'Пётр', lesson_id: 'real-9', grade: '5',
    student_id: 'stud:petrov' })
  const grades = outbox.pending.value.filter((e) => e.kind === 'grade')
  assert.equal(grades.length, 1, 'правка встала РЯДОМ с прежней, а не вместо неё')
  assert.equal(grades[0].payload.grade, '5')
})
