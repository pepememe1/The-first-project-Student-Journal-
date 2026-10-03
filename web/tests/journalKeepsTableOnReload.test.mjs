// journalKeepsTableOnReload.test.mjs — перечитывание журнала не убирает таблицу с экрана.
//
// 🔥 Дефект (01.10.2026, жалоба Ярослава): «ставим оценку — всё автосохраняется, а потом
// отматывает в верх списка». После каждой оценки журнал перечитывается, а шаблон на время
// загрузки показывал ВМЕСТО таблицы строку «Загрузка…» (`v-else-if="loading"`): страница
// схлопывалась, прокрутка вставала наверх, фокус уходил с ячейки. Ни сборка, ни линтер
// этого не видят — нужна проверка условия, при котором таблица исчезает.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

//Переводы строк приводим к LF: файл в рабочей копии может быть с CRLF, и обратный ход,
//ищущий многострочный фрагмент, иначе не нашёл бы, что ломать.
const SRC = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
  .replace(/\r\n/g, '\n')

/** Надпись «Загрузка…» заменяет таблицу только когда на экране журнал ДРУГОЙ пары. */
function placeholderOnlyForAnotherJournal(src) {
  const line = src.split('\n').find((l) => l.includes("locale.t('common.loading')") && l.includes('v-else-if='))
  if (!line) return false
  const cond = line.match(/v-else-if="([^"]+)"/)[1]
  return cond.includes('loading') && cond.includes('shownKey !== journalKey')
}

/** Ответ применяется только на ПОСЛЕДНИЙ запрос (иначе старый ответ откатит оценку). */
function onlyLatestAnswerApplies(src) {
  const at = src.indexOf('async function load()')
  const body = src.slice(at, src.indexOf('\n}\n', at))
  const guard = body.indexOf('if (seq !== loadSeq) return')
  const apply = body.indexOf('data.value = fresh')
  return guard > 0 && apply > guard && /const seq = \+\+loadSeq/.test(body)
}

test('перечитывание того же журнала не убирает таблицу', () => {
  assert.equal(placeholderOnlyForAnotherJournal(SRC), true)
})

test('обратный ход: прежнее условие «loading» проверка ловит', () => {
  const broken = SRC.replace('v-else-if="loading && shownKey !== journalKey"', 'v-else-if="loading"')
  assert.notEqual(broken, SRC, 'обратный ход не нашёл строку, которую ломает')
  assert.equal(placeholderOnlyForAnotherJournal(broken), false)
})

test('применяется ответ только на последний запрос журнала', () => {
  assert.equal(onlyLatestAnswerApplies(SRC), true)
})

test('обратный ход: без проверки номера запроса проверка краснеет', () => {
  const broken = SRC.replace('    if (seq !== loadSeq) return\n    data.value = fresh', '    data.value = fresh')
  assert.notEqual(broken, SRC, 'обратный ход не нашёл строку, которую ломает')
  assert.equal(onlyLatestAnswerApplies(broken), false)
})
