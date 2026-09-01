/**
 * journalMarks.test.mjs — какие отметки преподаватель может поставить РУКОЙ.
 *
 * 🔥 ЗАЧЕМ. До 01.09.2026 у практики в журнале не было вариантов «Б» и «О» вовсе —
 * только «Н». При этом сервер обе метки принимает (`grading.is_allowed_value`), а
 * голосовая команда («Иванов болел», `voice_command._ABSENCE_B`) ставит их на ЛЮБОМ типе
 * занятия. То есть одно и то же действие было доступно голосом и недоступно рукой; хуже
 * того, поставленные голосом «Б» на практике до 31.08.2026 молча терялись в подсчёте
 * пропусков (`webdata.absences` учитывала у практики одну метку из трёх).
 *
 * Здесь проверяется НАБОР ВАРИАНТОВ — единственное место, где рассинхрон между голосом,
 * рукой и сервером виден без запуска браузера.
 *
 * ⚠️ ДЗ намеренно БЕЗ «Б»/«О»: домашняя работа делается вне аудитории, «Н» там значит
 * «не сдал», а не «не был» — по той же причине ДЗ не входит в посещаемость. Это тоже
 * закреплено тестом: «добавить симметрично» выглядит логично и было бы ошибкой.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const SRC = readFileSync(new URL('../src/pages/teacher/TeacherJournal.vue', import.meta.url), 'utf8')

/** Тело функции cellOptions из продукта — читаем ЕГО, а не пересказ. */
function cellOptionsBody() {
  const at = SRC.indexOf('function cellOptions(l) {')
  assert.notEqual(at, -1, 'функция cellOptions пропала — тест проверяет не то')
  return SRC.slice(at, SRC.indexOf('\n}', at))
}

test('практика даёт поставить «Б» и «О», а не только «Н»', () => {
  const body = cellOptionsBody()
  const practice = body.split('\n').find((l) => l.includes("l.type === 'Практика'"))
  assert.ok(practice, 'у практики нет собственной ветки — значит «Б»/«О» ей недоступны')
  assert.ok(
    practice.includes('ATTENDANCE_MARKS'),
    'практика не получает полный набор отметок посещаемости: поставить «болел» рукой нельзя, ' +
      'хотя голосом можно и сервер это принимает',
  )
})

test('набор отметок посещаемости — ровно Н, Б, О', () => {
  const m = SRC.match(/const ATTENDANCE_MARKS = \[([^\]]+)\]/)
  assert.ok(m, 'ATTENDANCE_MARKS исчез')
  const marks = m[1].split(',').map((s) => s.trim().replace(/['"]/g, ''))
  assert.deepEqual(marks, ['Н', 'Б', 'О'])
})

test('у ДЗ «Б» и «О» НЕТ — и это намеренно', () => {
  const body = cellOptionsBody()
  const other = body.split('\n').find((l) => l.includes('PRACTICE_TYPES.includes'))
  assert.ok(other, 'ветка для остальных практикоподобных типов пропала')
  assert.ok(
    !other.includes('ATTENDANCE_MARKS') && other.includes("'Н'"),
    'ДЗ получило отметки посещаемости: домашняя работа делается вне аудитории, ' +
      '«Н» там значит «не сдал», а не «не был» (по той же причине ДЗ не идёт в пропуски)',
  )
})

test('лекция сохранила свой набор', () => {
  const m = SRC.match(/'Лекция':\s*\[([^\]]+)\]/)
  assert.ok(m, 'набор для лекции пропал')
  const opts = m[1].split(',').map((s) => s.trim().replace(/['"]/g, ''))
  for (const mark of ['Н', 'Б', 'О', '✓']) {
    assert.ok(opts.includes(mark), `у лекции пропала отметка «${mark}»`)
  }
})
