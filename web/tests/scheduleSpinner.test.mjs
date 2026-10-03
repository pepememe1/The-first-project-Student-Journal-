// scheduleSpinner.test.mjs — «Загрузка расписания…» обязана сниматься.
//
// Живой прогон 01.10.2026: у студента крутилка висела >30 с без ошибки. Две причины:
//  • у списка групп и у расписания был ОБЩИЙ счётчик запросов: `load()` студента группы
//    не колледжа звал `loadGroupsList()`, тот сдвигал счётчик, и `finally` в `load()` уже
//    не снимал «Загрузка…» НИКОГДА;
//  • своё расписание ждало список групп, при недоступном портале — 20 + 20 с.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../src/pages/SchedulePage.vue', import.meta.url), 'utf8')
  .replace(/\r\n/g, '\n')

function fnBody(text, head) {
  const at = text.indexOf(head)
  assert.ok(at >= 0, `нет ${head}`)
  return text.slice(at, text.indexOf('\n}\n', at))
}

/** Список групп не трогает счётчик расписания. */
function listHasOwnToken(text) {
  const body = fnBody(text, 'async function loadGroupsList()')
  return /\+\+listSeq/.test(body) && !/nextReq\(\)|reqSeq/.test(body)
}

test('у списка групп свой счётчик запросов', () => {
  assert.ok(listHasOwnToken(src), 'loadGroupsList снова сдвигает счётчик load()')
})

test('обратный ход: общий счётчик проверка ловит', () => {
  const broken = src.replace('const my = ++listSeq', 'const my = nextReq()')
  assert.notEqual(broken, src)
  assert.ok(!listHasOwnToken(broken))
})

test('своё расписание студента не ждёт списка групп', () => {
  const body = fnBody(src, 'async function enterCategory(')
  const tail = body.slice(body.indexOf("mode.value = 'group'"))
  const firstLoad = tail.indexOf('await load()')
  assert.ok(firstLoad >= 0)
  assert.doesNotMatch(tail.slice(0, firstLoad), /await loadGroupsList\(\)/,
    'студент снова ждёт список групп перед своим расписанием')
})
