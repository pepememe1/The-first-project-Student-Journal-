// grading.contract.test.mjs — JS-сторона контракта кастомных шкал оценок (§ролей, 3.3.1).
//
// Прогоняет web/src/utils/grading.js по ТОМУ ЖЕ golden-файлу, что и Python
// (tests/test_grade_contract.py). Запуск: cd web && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { toFivePoint, isFailedScaled, practiceAverage } from '../src/utils/grading.js'

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
