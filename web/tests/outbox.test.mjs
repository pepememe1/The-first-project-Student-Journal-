// outbox.test.mjs — очередь оценок, выставленных без сети (web/src/api/outbox.js).
//
// Проверяется то, из-за чего преподаватель может ПОТЕРЯТЬ РАБОТУ или отправить не то:
// схлопывание повторных правок одной клетки, переживание выхода из аккаунта, отказ
// отправлять чужую очередь, разное обращение с обрывом связи и с отказом по существу.
//
// ⚠️ localStorage и window подставляем сами: модуль читает их при загрузке (это его
// хранилище), а node --test работает без браузера. Подмена стоит десяток строк и
// позволяет держать сторож там же, где остальные веб-тесты, — иначе очередь можно
// было бы проверить только вручную на живом телефоне, то есть практически никогда.
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
    _dump: () => [...m.keys()],
  }
}

globalThis.localStorage = memoryStorage()
globalThis.window = { localStorage: globalThis.localStorage }

const outbox = await import('../src/api/outbox.js')

function loginAs(login) {
  localStorage.setItem('gb.user', JSON.stringify({ login, role: 'teacher' }))
  outbox.reloadOutbox()
}

function cell(n, grade) {
  return { surname: 'Иванов', name: `Студент${n}`, lesson_id: 'les-1', grade }
}

test('правка одной клетки схлопывается в одну запись с последним значением', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '3'))
  outbox.enqueueGrade(cell(1, '4'))
  outbox.enqueueGrade(cell(1, '5'))
  assert.equal(outbox.pending.value.length, 1, 'три нажатия — одна запись')
  assert.equal(outbox.pending.value[0].payload.grade, '5')
})

test('разные клетки не схлопываются и хранят порядок постановки', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(2, '4'))
  assert.equal(outbox.pending.value.length, 2)
  assert.deepEqual(outbox.pending.value.map((e) => e.payload.name),
    ['Студент1', 'Студент2'])
})

test('снятие оценки — это пустое значение, а не пропуск записи', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(1, ''))
  assert.equal(outbox.pending.value.length, 1)
  assert.equal(outbox.pending.value[0].payload.grade, '',
    'сервер понимает пустую строку как надгробие — её и надо отправить')
})

test('очередь переживает выход из аккаунта', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(7, '4'))
  // выход: приложение стирает визитку и кэш, но НЕ очередь
  localStorage.removeItem('gb.user')
  outbox.reloadOutbox()
  assert.equal(outbox.pending.value.length, 0, 'без визитки очередь не показываем')
  loginAs('teach1')
  assert.equal(outbox.pending.value.length, 1, 'после входа работа на месте')
  assert.equal(outbox.pending.value[0].payload.grade, '4')
})

test('чужая очередь не видна и не отправляется', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(9, '2'))

  loginAs('teach2')
  assert.equal(outbox.pending.value.length, 0, 'вошёл другой — чужих записей нет')

  let calls = 0
  outbox.setSender(async () => { calls += 1 })
  await outbox.flushOutbox()
  assert.equal(calls, 0, 'под чужим токеном отправлять нечего')

  loginAs('teach1')
  assert.equal(outbox.pending.value.length, 1, 'у автора запись сохранилась')
})

test('успешная отправка убирает запись из очереди', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(2, '4'))

  const sent = []
  outbox.setSender(async (e) => { sent.push(e.payload) })
  const stats = await outbox.flushOutbox()

  assert.equal(stats.sent, 2)
  assert.equal(outbox.pending.value.length, 0)
  assert.deepEqual(sent.map((p) => p.grade), ['5', '4'])
})

test('обрыв связи НЕ теряет записи и не помечает их отвергнутыми', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(2, '4'))

  // Ошибка БЕЗ response — именно так axios сообщает, что запрос не дошёл.
  outbox.setSender(async () => { throw new Error('network down') })
  const stats = await outbox.flushOutbox()

  assert.equal(stats.sent, 0)
  assert.equal(outbox.pending.value.length, 2, 'ничего не потеряли')
  assert.equal(outbox.rejected.value.length, 0, 'связь пропала — это не отказ сервера')
})

test('отказ по существу уходит в отвергнутые, а не крутится вечно', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))

  outbox.setSender(async () => {
    const err = new Error('rejected')
    err.response = { status: 404, data: { detail: 'Занятие не найдено' } }
    throw err
  })
  const stats = await outbox.flushOutbox()

  assert.equal(stats.rejected, 1)
  assert.equal(outbox.pending.value.length, 0, 'повторять бессмысленно')
  assert.equal(outbox.rejected.value.length, 1)
  assert.equal(outbox.rejected.value[0].reason, 'Занятие не найдено',
    'человеку нужна причина, а не «не отправилось»')
})

test('истёкшая сессия останавливает выгрузку, ничего не теряя', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(2, '4'))

  outbox.setSender(async () => {
    const err = new Error('unauthorized')
    err.response = { status: 401, data: {} }
    throw err
  })
  await outbox.flushOutbox()

  assert.equal(outbox.pending.value.length, 2, 'войдёт заново — всё уедет')
  assert.equal(outbox.rejected.value.length, 0)
})

test('запись, которую сервер стабильно не принимает, становится видимой', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))

  outbox.setSender(async () => {
    const err = new Error('server error')
    err.response = { status: 500, data: {} }
    throw err
  })
  for (let i = 0; i < 6; i += 1) await outbox.flushOutbox()

  assert.equal(outbox.pending.value.length, 0)
  assert.equal(outbox.rejected.value.length, 1,
    'молча висеть в очереди навсегда она не имеет права')
})

test('pendingGrade показывает неотправленное значение для клетки', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(3, '4'))
  assert.equal(outbox.pendingGrade('les-1', 'Иванов', 'Студент3'), '4')
  assert.equal(outbox.pendingGrade('les-1', 'Иванов', 'НетТакого'), undefined)
})

// ───────────── занятия, домашка и перепривязка временных id ─────────────
//
// Занятие получает id на СЕРВЕРЕ, а оценки по нему преподаватель ставит сразу. Значит
// офлайн они ссылаются на временный id, и после создания их надо переписать. Это самая
// хрупкая часть очереди: ошибись здесь — и оценки по свежесозданной домашке будут вечно
// биться о несуществующее занятие, причём молча.

test('созданное офлайн занятие видно журналу до отправки', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  const tmp = outbox.enqueueLessonCreate({
    group: 'К74/1', subject: 'Физика', type: 'ДЗ', topic: 'Параграф 5',
  })
  assert.ok(outbox.isTempId(tmp), 'id временный и отличим от настоящего')
  const shown = outbox.pendingLessons('К74/1', 'Физика')
  assert.equal(shown.length, 1)
  assert.equal(shown[0].id, tmp)
  assert.equal(shown[0].topic, 'Параграф 5')
  assert.equal(outbox.pendingLessons('К74/1', 'Химия').length, 0, 'чужой предмет не мешаем')
})

test('после создания занятия оценки по нему уезжают с НАСТОЯЩИМ id', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  const tmp = outbox.enqueueLessonCreate({ group: 'К74/1', subject: 'Физика', type: 'ДЗ' })
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Пётр', lesson_id: tmp, grade: '5' })

  const seen = []
  outbox.setSender(async (e) => {
    seen.push({ kind: e.kind, lesson: e.payload.lesson_id })
    if (e.kind === 'lesson.create') return { data: { id: 'real-42' } }
    return { data: { ok: true } }
  })
  const stats = await outbox.flushOutbox()

  assert.equal(stats.sent, 2)
  assert.equal(seen[0].kind, 'lesson.create', 'занятие обязано уехать первым')
  assert.equal(seen[1].lesson, 'real-42', 'оценка ушла на настоящий id, а не на tmp')
})

test('связь оборвалась сразу после создания — оценка уже знает настоящий id', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  const tmp = outbox.enqueueLessonCreate({ group: 'К74/1', subject: 'Физика', type: 'ДЗ' })
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Пётр', lesson_id: tmp, grade: '4' })

  outbox.setSender(async (e) => {
    if (e.kind === 'lesson.create') return { data: { id: 'real-7' } }
    throw new Error('network down')     // оценка не доехала
  })
  await outbox.flushOutbox()

  assert.equal(outbox.pending.value.length, 1)
  assert.equal(outbox.pending.value[0].payload.lesson_id, 'real-7',
    'иначе оценка вечно билась бы о несуществующее занятие')
})

test('занятие не создалось — оценки по нему не висят в очереди молча', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  const tmp = outbox.enqueueLessonCreate({ group: 'К74/1', subject: 'Физика', type: 'ДЗ' })
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Пётр', lesson_id: tmp, grade: '5' })

  outbox.setSender(async (e) => {
    if (e.kind === 'lesson.create') {
      const err = new Error('no')
      err.response = { status: 403, data: { detail: 'Предмет вам не назначен' } }
      err.response.status = 403
      throw err
    }
    return { data: {} }
  })
  // 403 на первой попытке трактуется как «сессия/устройство» и останавливает выгрузку,
  // поэтому вторым проходом получаем именно отказ по существу.
  await outbox.flushOutbox()
  await outbox.flushOutbox()

  assert.equal(outbox.pending.value.length, 0, 'ни занятие, ни оценка не зависли')
  assert.equal(outbox.rejected.value.length, 2, 'обе записи показаны человеку')
})

test('правка ещё не уехавшего занятия вливается в его создание', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  const tmp = outbox.enqueueLessonCreate({
    group: 'К74/1', subject: 'Физика', type: 'ДЗ', topic: 'старая',
  })
  outbox.enqueueLessonUpdate(tmp, { topic: 'новая' })

  assert.equal(outbox.pending.value.length, 1, 'создать и тут же поправить — одна запись')
  assert.equal(outbox.pending.value[0].kind, 'lesson.create')
  assert.equal(outbox.pending.value[0].payload.topic, 'новая')
})

test('удаление не уехавшего занятия убирает и его, и оценки по нему', () => {
  loginAs('teach1')
  outbox.clearOutbox()
  const tmp = outbox.enqueueLessonCreate({ group: 'К74/1', subject: 'Физика', type: 'ДЗ' })
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Пётр', lesson_id: tmp, grade: '5' })
  outbox.enqueueLessonDelete(tmp)

  assert.equal(outbox.pending.value.length, 0,
    'создавать на сервере, чтобы тут же удалить, — лишний круг и лишние письма студентам')
})

test('посещаемость идёт тем же путём, что и оценка', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueGrade({ surname: 'Иванов', name: 'Пётр', lesson_id: 'les-9', grade: 'Н' })

  const sent = []
  outbox.setSender(async (e) => { sent.push(e); return { data: {} } })
  await outbox.flushOutbox()

  assert.equal(sent.length, 1)
  assert.equal(sent[0].kind, 'grade')
  assert.equal(sent[0].payload.grade, 'Н', 'Н/Б/О — это то же поле, что и балл')
})

test('итоговая оценка за семестр тоже ждёт сети', async () => {
  loginAs('teach1')
  outbox.clearOutbox()
  outbox.enqueueTermGrade({
    group: 'К74/1', subject: 'Физика', surname: 'Иванов', name: 'Пётр',
    grade: '5', form: 'Экзамен',
  })
  outbox.enqueueTermGrade({
    group: 'К74/1', subject: 'Физика', surname: 'Иванов', name: 'Пётр',
    grade: '4', form: 'Экзамен',
  })
  assert.equal(outbox.pending.value.length, 1, 'исправление схлопывается, как и оценка')

  const sent = []
  outbox.setSender(async (e) => { sent.push(e); return { data: {} } })
  await outbox.flushOutbox()
  assert.equal(sent[0].kind, 'term')
  assert.equal(sent[0].payload.grade, '4')
})
