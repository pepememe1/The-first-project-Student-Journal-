// mascot.contract.test.mjs — JS-сторона контракта выбора эмоции маскота.
//
// Прогоняет web/src/config/mascot.js::pickEmote по ТОМУ ЖЕ golden-файлу, что и Python
// (tests/test_mascot_contract.py). Расхождение приоритетов веток уронит один из тестов.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { pickEmote } from '../src/config/mascot.js'

const here = dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(
  readFileSync(resolve(here, '../../docs/contracts/mascot-cases.json'), 'utf-8')
).pick

test('pickEmote совпадает с общим контрактом маскота (Python↔JS)', () => {
  for (const c of cases) {
    assert.equal(
      pickEmote(c.state, c.mood, c.intent),
      c.expected,
      `pickEmote(${c.state}, ${c.mood}, ${c.intent}) должно быть ${c.expected}`
    )
  }
})
