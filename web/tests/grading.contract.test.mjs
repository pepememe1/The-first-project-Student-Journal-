// grading.contract.test.mjs — JS-сторона контракта кастомных шкал оценок (§ролей, 3.3.1).
//
// Прогоняет web/src/utils/grading.js по ТОМУ ЖЕ golden-файлу, что и Python
// (tests/test_grade_contract.py). Запуск: cd web && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { toFivePoint, isFailedScaled, practiceAverage, groupAverage } from '../src/utils/grading.js'

const here = dirname(fileURLToPath(import.meta.url))
const contract = JSON.parse(
  readFileSync(resolve(here, '../../docs/contracts/grade-cases.json'), 'utf-8')
)

test('toFivePoint совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of contract.to_five_point) {
    assert.equal(
      toFivePoint(c.raw, c.scale),
      c.expected,
      `toFivePoint(${JSON.stringify(c.raw)}, ${c.scale}) должно быть ${c.expected}`
    )
  }
})

test('isFailedScaled совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of contract.is_failed_scaled) {
    assert.equal(
      isFailedScaled(c.raw, c.scale),
      c.expected,
      `isFailedScaled(${JSON.stringify(c.raw)}, ${c.scale}) должно быть ${c.expected}`
    )
  }
})

// practiceAverage — офлайн-порт grading.practice_average (расчёт среднего на телефоне
// без сети). Случаи сгенерированы прогоном настоящей Python-функции, не написаны руками.
test('practiceAverage совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of contract.practice_average) {
    assert.equal(
      practiceAverage(c.items, c.records, c.cfg, c.scale),
      c.expected,
      `practiceAverage(${c._case}) должно быть ${c.expected}`
    )
  }
})

// Средний группы (20.10.2026) — один расчёт на продукт. Журнал преподавателя считал его
// своей формулой через toFixed(2): на 3.625 он давал 3.63, сервер — 3.62.
test('groupAverage совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of contract.group_average) {
    assert.equal(groupAverage(c.values), c.expected, `groupAverage(${c._case}) должно быть ${c.expected}`)
  }
})

test('журнал преподавателя не считает средний группы своей формулой', () => {
  const src = readFileSync(resolve(here, '../src/pages/teacher/TeacherJournal.vue'), 'utf-8')
  assert.match(src, /groupAverageOf\(/, 'средний группы обязан идти через grading.js::groupAverage')
  assert.doesNotMatch(src, /reduce\(\(a, b\) => a \+ b, 0\) \/ vals\.length\)\.toFixed/, 'вернулась своя формула')
})
