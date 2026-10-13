/**
 * journalFoolproof.test.mjs — журнал преподавателя прощает ошибки (13.10.2026).
 *
 * Живой обход стенда «глазами новичка» нашёл в журнале пять мест, где человек молча терял
 * работу или делал непоправимое:
 *   1. окно удаления занятия не называло ни даты, ни числа отметок;
 *   2. окно «Итоговые оценки» по «Закрыть» выбрасывало выбранное без вопроса;
 *   3. занятие создавалось с датой 01.01.2099 и с номером, который уже есть;
 *   4. у сохранённой оценки не было никакого знака «сохранено»;
 *   5. журнал каждый раз открывался на первой группе списка.
 *
 * Правила (`utils/lessonChecks.js`, `utils/lastChoice.js`) проверяются ПОВЕДЕНИЕМ, проводка
 * в странице — коротко и отдельно.
 * ⚠️ ОБРАТНЫЙ ХОД: `guardedClose` ниже натравливается на прежнюю разметку окна
 * (`@click.self="showAtt = false"`) и обязана её отвергнуть.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  parseRuDate, lessonDateIssue, lessonMarkCount, duplicateLesson, lessonNumberOk, FAR_DATE_DAYS,
} from '../src/utils/lessonChecks.js'
import { recallChoice, rememberChoice, pickRemembered } from '../src/utils/lastChoice.js'

const page = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')
const TODAY = new Date(2026, 9, 13)          // 13.10.2026

test('дата занятия: принимается только настоящая дата вида дд.мм.гггг', () => {
  assert.ok(parseRuDate('13.10.2026'))
  for (const bad of ['31.02.2026', '32.01.2026', '13.13.2026', '1.1.26', '2026-10-13', 'завтра', '13/10/2026']) {
    assert.equal(parseRuDate(bad), null, `приняли «${bad}» за дату`)
    assert.equal(lessonDateIssue(bad, TODAY), 'format')
  }
})

test('дата занятия: пустая разрешена, близкая годится, далёкая переспрашивается', () => {
  assert.equal(lessonDateIssue('', TODAY), '')
  assert.equal(lessonDateIssue('13.10.2026', TODAY), '')
  assert.equal(lessonDateIssue('01.09.2026', TODAY), '')          // начало семестра — задним числом
  assert.equal(lessonDateIssue('01.01.2099', TODAY), 'far')       // дефект из обхода
  assert.equal(lessonDateIssue('13.10.2025', TODAY), 'far')       // опечатка в годе
  assert.equal(lessonDateIssue('13.10.1990', TODAY), 'far')
})

test('граница «далеко»: ровно порог ещё годится, на день дальше — уже вопрос', () => {
  const at = (days) => {
    const d = new Date(TODAY.getFullYear(), TODAY.getMonth(), TODAY.getDate() + days)
    return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}`
  }
  assert.equal(lessonDateIssue(at(FAR_DATE_DAYS), TODAY), '')
  assert.equal(lessonDateIssue(at(FAR_DATE_DAYS + 1), TODAY), 'far')
  assert.equal(lessonDateIssue(at(-FAR_DATE_DAYS - 1), TODAY), 'far')
})

test('сколько отметок пропадёт вместе с занятием — считаем и пересдачи, и пропуски', () => {
  const students = [
    { grades: { L1: '5', L2: '4' } },
    { grades: { L1: 'Н', L1_retake: '3 (Зачтено)' } },
    { grades: { L1: '', L1_retake_2: '4' } },
    { grades: {} },
    {},
  ]
  assert.equal(lessonMarkCount('L1', students), 4)
  assert.equal(lessonMarkCount('L2', students), 1)
  assert.equal(lessonMarkCount('L3', students), 0)
  assert.equal(lessonMarkCount('L1', undefined), 0)
})

test('дубль номера: тот же тип и номер в той же подгруппе', () => {
  const lessons = [
    { id: 'a', type: 'Практика', number: 6, subgroup: 0, date: '13.10.2026' },
    { id: 'b', type: 'Лекция', number: 6, subgroup: 0 },
    { id: 'c', type: 'Практика', number: 1, subgroup: 1 },
  ]
  assert.equal(duplicateLesson(lessons, { type: 'Практика', number: 6 })?.id, 'a')
  assert.equal(duplicateLesson(lessons, { type: 'Практика', number: '6' })?.id, 'a')
  assert.equal(duplicateLesson(lessons, { type: 'Практика', number: 7 }), null)
  // Само занятие при правке себе не дубль.
  assert.equal(duplicateLesson(lessons, { type: 'Практика', number: 6, exceptId: 'a' }), null)
  // У другой подгруппы своя нумерация — «Практика №1» есть у обеих.
  assert.equal(duplicateLesson(lessons, { type: 'Практика', number: 1, subgroup: 2 }), null)
  assert.equal(duplicateLesson(lessons, { type: 'Практика', number: 1, subgroup: 1 })?.id, 'c')
})

test('номер занятия — целое от 1 до 999', () => {
  for (const ok of [1, 6, 999, '12']) assert.equal(lessonNumberOk(ok), true, String(ok))
  for (const bad of [0, -5, 1000, 1.5, '', 'abc', null, undefined]) assert.equal(lessonNumberOk(bad), false, String(bad))
})

function memory() {
  const m = new Map()
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
    keys: () => [...m.keys()] }
}

test('журнал помнит группу и предмет человека — и только его', () => {
  const store = memory()
  rememberChoice('semenova', { group: 'К74/1', subject: 'Базы данных' }, { store })
  assert.deepEqual(recallChoice('semenova', { store }), { group: 'К74/1', subject: 'Базы данных' })
  assert.deepEqual(recallChoice('orlov', { store }), {}, 'чужой выбор достался следующему за компьютером')
  // Пустое значение (страница ещё грузится) прежний выбор не затирает.
  rememberChoice('semenova', { group: '', subject: 'Математика' }, { store })
  assert.deepEqual(recallChoice('semenova', { store }), { group: 'К74/1', subject: 'Математика' })
  assert.ok(!store.keys().join(' ').includes('semenova'), 'логин лёг в ключ хранилища')
})

test('запомненное — подсказка: чего нет в списке сервера, то не выбирается', () => {
  const groups = ['К64/2', 'К74/1']
  assert.equal(pickRemembered(groups, '', 'К74/1'), 'К74/1')
  assert.equal(pickRemembered(groups, 'К64/2', 'К74/1'), 'К64/2', 'ссылка главнее памяти')
  assert.equal(pickRemembered(groups, '', 'К99/9'), 'К64/2', 'группу сняли с преподавателя — берём первую')
  assert.equal(pickRemembered(groups, 'чужая', ''), 'К64/2')
  assert.equal(pickRemembered([], '', 'К74/1'), '')
})

/** Окно закрывается через функцию-сторожа, а не прямым присваиванием? */
function guardedClose(src, flag, guard) {
  const direct = new RegExp(`@click(\\.self)?="${flag} = false"`)
  return !direct.test(src) && new RegExp(`@click\\.self="${guard}"`).test(src)
}

test('проводка: окна занятия и итоговых оценок не закрываются мимо вопроса', () => {
  assert.equal(guardedClose(page, 'showAtt', 'closeAtt'), true, 'итоговые оценки снова теряются по «Закрыть»')
  assert.equal(guardedClose(page, 'showLesson', 'closeLesson'), true, 'набранная тема снова стирается щелчком мимо')
  // обратный ход: прежнюю разметку проверка отвергает
  assert.equal(guardedClose('<div v-dialog @click.self="showAtt = false">', 'showAtt', 'closeAtt'), false)
  assert.match(page, /attChanged\.value\) \{\s+const ok = await confirm/)
  assert.match(page, /@click="vedomostFromAtt"/, 'ведомость из окна аттестации скачивается мимо предупреждения о несохранённом')
})

test('проводка: окно удаления называет дату и число отметок, после удаления — сообщение', () => {
  assert.match(page, /message: deleteLessonText\(l\)/)
  assert.match(page, /lessonMarkCount\(l\.id, data\.value\?\.students\)/)
  assert.match(page, /teacherJournal\.deleteLessonFinal/)
  assert.match(page, /toast\.success\(locale\.t\('teacherJournal\.lessonDeleted'/)
})

test('проводка: форма занятия проверяется ДО отправки, оценка получает знак «сохранено»', () => {
  const save = page.slice(page.indexOf('async function saveLesson()'), page.indexOf('async function delLesson'))
  const check = save.indexOf('await lessonFormOk()')
  const send = save.indexOf('teacherApi.createLesson')
  assert.ok(check > 0 && check < send, 'проверка формы стоит после отправки или пропала')
  const grade = page.slice(page.indexOf('async function setGrade('), page.indexOf('function plusDays'))
  assert.ok(grade.indexOf('markSaved(s, key)') > grade.indexOf('await teacherApi.setGrade('),
    '«сохранено» показывается до ответа сервера — это обещание, а не факт')
  assert.match(page, /teacherJournal\.savedAt/)
  assert.match(page, /teacherJournal\.clearMark/, 'пункт «убрать отметку» снова без подписи')
})

test('проводка: журнал открывается на запомненной группе и запоминает выбор', () => {
  assert.match(page, /pickRemembered\(groups\.value, qGroup, last\.group\)/)
  assert.match(page, /rememberChoice\(auth\.user\?\.login, \{ group: g, subject: s \}\)/)
})
