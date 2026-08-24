/**
 * subgroupSelection.test.mjs — выбранная подгруппа в журнале преподавателя (25.08.2026).
 *
 * Живой отчёт: «если в предмете с раздельным обучением выбрать одну подгруппу и поставить
 * кому-то оценку, то перекидывает в совместку, и надо заново выбирать подгруппу».
 *
 * Причина не в простановке оценки, а в вотчере. `splitOwned` — это computed поверх
 * `data`, и он отдаёт НОВЫЙ массив при каждой загрузке журнала, даже когда состав
 * подгрупп не изменился ни на йоту. Vue сравнивает результат по ССЫЛКЕ, поэтому watch
 * срабатывал после КАЖДОГО обновления — а простановка оценки как раз перезагружает
 * журнал. Прежнее тело вотчера безусловно ставило 0 («Совместно»).
 *
 * Проверять поведение Vue без запуска приложения нельзя, поэтому здесь — форма кода:
 * сторож обязан краснеть, если вернётся безусловный сброс. Обратный ход проверен.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
const journal = readFileSync(join(WEB, 'src/pages/teacher/TeacherJournal.vue'), 'utf8')

// Тело вотчера по splitOwned — только оно, чтобы совпадения в соседнем коде не считались.
const watcher = (() => {
  const i = journal.indexOf('watch(splitOwned,')
  assert.ok(i > 0, 'вотчер по splitOwned исчез — проверь, чем его заменили')
  return journal.slice(i, journal.indexOf('function subgroupLabel'))
})()

test('перезагрузка журнала не сбрасывает выбранную подгруппу', () => {
  assert.doesNotMatch(
    watcher,
    /activeSubgroup\.value = owned\.length === 1 \? owned\[0\] : 0/,
    'вернулся безусловный сброс: после каждой оценки преподавателя будет выбрасывать в «Совместно»',
  )
  assert.match(
    watcher,
    /!owned\.includes\(activeSubgroup\.value\)/,
    'сброс должен происходить ТОЛЬКО когда прежний выбор стал невозможен',
  )
})

test('вотчер по-прежнему закрывает три состояния подгрупп', () => {
  // Ради починки нельзя потерять два законных случая: предмет без разделения и
  // преподаватель единственной своей подгруппы (кнопок нет, всё неявно под неё).
  assert.match(watcher, /if \(!owned\.length\) \{ activeSubgroup\.value = 0/,
    'предмет без раздельного обучения обязан сбрасывать выбор в 0')
  assert.match(watcher, /owned\.length === 1\) \{ activeSubgroup\.value = owned\[0\]/,
    'преподаватель одной подгруппы обязан получать именно её')
})

test('нераспределённые студенты названы вслух, а не пропадают молча', () => {
  // Серверная половина той же жалобы: студент без строки StudentSubgroup выпадал из
  // ростера вообще. Число приходит в split.unassigned, журнал обязан его показать.
  assert.match(journal, /data\.value\?\.split\?\.unassigned \|\| 0/,
    'журнал перестал читать число нераспределённых студентов')
  assert.match(journal, /v-if="unassignedCount"/,
    'предупреждение о нераспределённых студентах убрано — пропажа снова станет молчаливой')
  assert.match(journal, /teacherJournal\.unassignedWarning/,
    'текст предупреждения больше не берётся из словаря')
})
