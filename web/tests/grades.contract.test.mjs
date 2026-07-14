// grades.contract.test.mjs — JS-сторона контракта fail-логики оценок.
//
// Прогоняет web/src/utils/grades.js::isFailed по ТОМУ ЖЕ golden-файлу, что и Python
// (tests/test_grade_contract.py). Если реализации разойдутся — упадёт один из двух
// тестов. Встроенный node:test (без vitest) — ноль новых зависимостей.
// Запуск: cd web && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { isFailed, needsRetake } from '../src/utils/grades.js'

const here = dirname(fileURLToPath(import.meta.url))
const contract = JSON.parse(
  readFileSync(resolve(here, '../../docs/contracts/grade-cases.json'), 'utf-8')
)

test('isFailed совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of contract.is_failed) {
    assert.equal(
      isFailed(c.grade),
      c.expected,
      `isFailed(${JSON.stringify(c.grade)}) должно быть ${c.expected}`
    )
  }
})

test('needsRetake совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of contract.needs_retake) {
    assert.equal(
      needsRetake(c.records, c.lesson_id, c.ri),
      c.expected,
      `needsRetake(${JSON.stringify(c.records)}, ri=${c.ri}) должно быть ${c.expected}`
    )
  }
})
