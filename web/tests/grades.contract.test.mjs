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
import { isFailed } from '../src/utils/grades.js'

const here = dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(
  readFileSync(resolve(here, '../../docs/contracts/grade-cases.json'), 'utf-8')
).is_failed

test('isFailed совпадает с общим контрактом (Python↔JS)', () => {
  for (const c of cases) {
    assert.equal(
      isFailed(c.grade),
      c.expected,
      `isFailed(${JSON.stringify(c.grade)}) должно быть ${c.expected}`
    )
  }
})
