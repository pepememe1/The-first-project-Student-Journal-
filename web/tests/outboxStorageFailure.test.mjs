// outboxStorageFailure.test.mjs — отказ устройства не выдаётся за «сохранено офлайн»
// (находка ревью O01, 18.09.2026; починено 20.09.2026).
//
// ━━ ЧТО БЫЛО ━━
// Запись очереди на диск шла так: `try { localStorage.setItem(...) } catch { /* квота
// переполнена — очередь короткая, терять нечего */ }`. «Терять нечего» было неправдой:
// очередь и есть та работа преподавателя, которую он сделал без сети. Отказ выглядел
// как полный успех — журнал показывал «оценка сохранена и уйдёт, когда появится связь»,
// — а на диск не легло ничего. И добивала это следующая же выгрузка: она начинается с
// `reloadOutbox()`, тот честно читал пустой диск и затирал им память. Оценка исчезала,
// не дождавшись даже перезапуска вкладки.
//
// ⚠️ Проверяется ДВА следствия, и второе важнее первого: человеку видна правда
// (`storageFailed`) И очередь в памяти переживает перечитывание.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть тихий `catch` в `save()` — краснеют первый и второй
// тесты; убрать защиту памяти в `load()` — краснеет второй. Третий и четвёртый остаются
// зелёными и стерегут от «починки», которая объявила бы диск сломанным навсегда или
// показала бы чужую очередь после смены человека.
import { test } from 'node:test'
import assert from 'node:assert/strict'

function memoryStorage() {
  const m = new Map()
  const api = {
    failWrites: false,
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => {
      //Ключ `gb.user` пишет не очередь, а вход — его глушить нельзя, иначе тест
      //проверял бы «нет пользователя», а не «нет места».
      if (api.failWrites && k.startsWith('gb.outbox')) {
        const e = new Error('QuotaExceededError')
        e.name = 'QuotaExceededError'
        throw e
      }
      m.set(k, String(v))
    },
    removeItem: (k) => m.delete(k),
    clear: () => m.clear(),
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size },
  }
  return api
}

const store = memoryStorage()
globalThis.localStorage = store
globalThis.window = { localStorage: store }

const outbox = await import('../src/api/outbox.js')

function loginAs(login) {
  store.setItem('gb.user', JSON.stringify({ login, role: 'teacher' }))
  outbox.reloadOutbox()
}

const cell = (n, grade) => ({ surname: 'Иванов', name: `Студент${n}`, lesson_id: 'les-1', grade })

test('отказ записи на диск виден, а не выдаётся за успех', () => {
  loginAs('alice')
  outbox.clearOutbox()
  store.failWrites = true
  try {
    outbox.enqueueGrade(cell(1, '5'))
    assert.equal(outbox.storageFailed.value, true,
      'диск отказал, а продукт этого не заметил — человеку сказали «сохранено»')
  } finally {
    store.failWrites = false
  }
})

test('несохранённая очередь не затирается пустым диском', () => {
  loginAs('alice')
  outbox.clearOutbox()
  store.failWrites = true
  try {
    outbox.enqueueGrade(cell(2, '4'))
    assert.equal(outbox.pending.value.length, 1, 'подготовка: запись обязана быть в памяти')

    //Ровно то, с чего начинается КАЖДАЯ выгрузка.
    outbox.reloadOutbox()
    assert.equal(outbox.pending.value.length, 1,
      'перечитывание стёрло работу преподавателя пустым содержимым диска')
    assert.equal(outbox.pending.value[0].payload.name, 'Студент2')
  } finally {
    store.failWrites = false
  }
})

test('удачная запись гасит тревогу', () => {
  loginAs('alice')
  outbox.clearOutbox()
  store.failWrites = true
  try {
    outbox.enqueueGrade(cell(3, '3'))
  } finally {
    store.failWrites = false
  }
  assert.equal(outbox.storageFailed.value, true, 'подготовка: тревога должна гореть')

  outbox.enqueueGrade(cell(4, '5'))
  assert.equal(outbox.storageFailed.value, false,
    'диск снова пишет, а плашка висит — сигнал, который всегда красный, перестают читать')
})

test('смена человека перечитывает очередь даже при сломанном диске', () => {
  //Иначе защита памяти превратилась бы в утечку: чужая оценка осталась бы на экране
  //следующего человека и уехала бы на сервер от его имени (тот же класс, что O02).
  loginAs('alice')
  outbox.clearOutbox()
  store.failWrites = true
  try {
    outbox.enqueueGrade(cell(5, '2'))
    assert.equal(outbox.pending.value.length, 1)
    loginAs('bob')
    assert.equal(outbox.pending.value.length, 0,
      'очередь Алисы видна Бобу — защита памяти стала утечкой чужих данных')
  } finally {
    store.failWrites = false
  }
})
