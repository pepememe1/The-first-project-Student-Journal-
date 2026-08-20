// pollResult.test.mjs — итог опроса: кубок, ничья и три случая, когда победителя нет.
//
// Обратный ход (обязателен): убрать проверку `closed` — краснеет «в живом опросе
// победителя нет»; убрать проверку `max <= 0` — краснеет «нулевой опрос»; вернуть
// `indexOf(max)` вместо сбора всех лидеров — краснеет «ничья отмечает всех».
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { pollWinners } from '../src/utils/pollResult.js'

test('победитель — вариант с максимумом голосов', () => {
  assert.deepEqual(pollWinners([1, 5, 2], true), [1])
})

test('ничья отмечает ВСЕХ лидеров, а не первого из равных', () => {
  // Тихо назначить победителем первого по списку — соврать в самом заметном месте
  // карточки: рядом стоит вариант с тем же числом голосов.
  assert.deepEqual(pollWinners([4, 4, 1], true), [0, 1])
  assert.deepEqual(pollWinners([3, 3, 3], true), [0, 1, 2])
})

test('в ЖИВОМ опросе победителя нет вовсе', () => {
  // Подсвеченный лидер тянет за собой голоса — опрос перестаёт мерить то, ради чего
  // затеян. Кубок появляется только после завершения.
  assert.deepEqual(pollWinners([9, 1], false), [])
})

test('никто не проголосовал — победителя нет', () => {
  // Иначе кубок достаётся первому варианту просто потому, что 0 === 0.
  assert.deepEqual(pollWinners([0, 0, 0], true), [])
})

test('нет распределения — нечего показывать', () => {
  // Распределение сервер отдаёт только автору (или всем при открытых голосах).
  assert.deepEqual(pollWinners(null, true), [])
  assert.deepEqual(pollWinners([], true), [])
  assert.deepEqual(pollWinners(undefined, true), [])
})

test('мусор в распределении не даёт ложного победителя', () => {
  assert.deepEqual(pollWinners([null, undefined, 'x'], true), [])
  assert.deepEqual(pollWinners(['2', 1], true), [0])
})

test('карточка опроса берёт победителя из общей функции, а не считает сама', () => {
  // Вторая копия правил разъехалась бы молча и именно в сторону «кубок виден раньше
  // времени»: в живом опросе это уже не косметика, а искажение самого опроса.
  const src = readFileSync(new URL('../src/components/activity/poll/PollMessage.vue',
    import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8')
  assert.ok(/pollWinners\(tally\.value,\s*closed\.value\)/.test(src),
    'победитель должен считаться общей функцией pollWinners')
  // Сужаем до расчёта ИМЕННО по распределению: обычный Math.max в файле есть и он
  // законный (обрезка обратного отсчёта по нулю).
  assert.ok(/Math\.max\(\s*\.\.\.\s*tally/.test(src) === false,
    'в карточке не должно быть второго расчёта максимума по распределению')
})

test('подпись автора опроса приходит с сервера, а не собирается на клиенте', () => {
  const src = readFileSync(new URL('../src/components/activity/poll/PollMessage.vue',
    import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8')
  assert.ok(/activity\.host_name/.test(src), 'карточка должна показывать автора опроса')
})
