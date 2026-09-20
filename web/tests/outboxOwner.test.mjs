// outboxOwner.test.mjs — очередь принадлежит тому, кто её поставил (находка ревью O02,
// 18.09.2026; починено 20.09.2026).
//
// ━━ ЧТО БЫЛО ━━
// Ответ сервера приходит ПОЗЖЕ отправки, а на общем компьютере колледжа за это время
// успевают смениться люди: A вышел, вошёл B. `save()` спрашивал логин В МОМЕНТ ЗАПИСИ,
// поэтому поздний отказ по запросу A дописывал фамилию студента и оценку A в очередь
// отклонённых у B — чужие данные появлялись на экране человека, который их не вводил.
// Вторая половина того же: остаток очереди A продолжал уезжать уже под сессией B, то
// есть запись данных одного человека от имени другого.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `flushOwner` из `save()` — краснеет первый тест;
// убрать проверку `currentLogin() !== owner` в цикле — краснеет второй.
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

const cell = (n, grade) => ({ surname: 'Иванов', name: `Студент${n}`, lesson_id: 'les-1', grade })

test('поздний отказ по записи A не попадает в отклонённые у B', async () => {
  loginAs('alice')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))

  //Отправка «зависает», и ровно в это время за компьютер садится другой человек.
  outbox.setSender(async () => {
    loginAs('bob')                       //смена аккаунта прямо во время ожидания
    const err = new Error('нет такого студента')
    err.response = { status: 422, data: { detail: 'Студент не найден в группе занятия' } }
    throw err
  })
  await outbox.flushOutbox()
  outbox.setSender(null)

  const atBob = JSON.parse(localStorage.getItem('gb.outbox.rejected.bob') || '[]')
  assert.equal(atBob.length, 0, 'запись Алисы попала в отклонённые к Бобу')

  const atAlice = JSON.parse(localStorage.getItem('gb.outbox.rejected.alice') || '[]')
  assert.equal(atAlice.length, 1, 'отказ обязан лечь владельцу записи')
  assert.equal(atAlice[0].payload.name, 'Студент1')
})

test('вход в ДРУГОЙ вкладке останавливает выгрузку этой', async () => {
  //⚠️ Смена делается БЕЗ `reloadOutbox`, и это не упрощение, а сам случай: соседняя
  //вкладка пишет `gb.user` в общий для origin localStorage, а модуль в ЭТОЙ вкладке
  //про смену не знает и продолжает держать очередь прежнего человека в памяти. Если
  //звать здесь `loginAs`, очередь перезагрузится сама и тест позеленеет независимо от
  //проверки владельца — то есть перестанет стеречь ровно то, ради чего написан
  //(проверено обратным ходом: без `currentLogin() !== owner` он обязан краснеть).
  const switchInAnotherTab = (login) =>
    localStorage.setItem('gb.user', JSON.stringify({ login, role: 'teacher' }))

  loginAs('alice')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(2, '4'))
  outbox.enqueueGrade(cell(3, '3'))

  const sent = []
  outbox.setSender(async (e) => {
    sent.push(e.payload.name)
    if (sent.length === 1) switchInAnotherTab('bob')
  })
  await outbox.flushOutbox()
  outbox.setSender(null)
  loginAs('alice')

  assert.equal(sent.length, 1,
    `под чужой сессией ушло ${sent.length} записей вместо одной: ${sent.join(', ')}`)
})

test('экран нового человека не показывает очередь предыдущего', async () => {
  loginAs('alice')
  outbox.clearOutbox()
  outbox.enqueueGrade(cell(1, '5'))
  outbox.enqueueGrade(cell(2, '4'))

  outbox.setSender(async () => { loginAs('bob') })
  await outbox.flushOutbox()
  outbox.setSender(null)

  assert.deepEqual(outbox.pending.value, [],
    'в памяти модуля осталась очередь прежнего пользователя')
})
