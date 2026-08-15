// mascot.contract.test.mjs — JS-сторона контракта выбора эмоции маскота.
//
// Прогоняет web/src/config/mascot.js::pickEmote по golden-файлу docs/contracts/
// mascot-cases.json.
//
// ⚠️ Раньше тот же файл читала Python-сторона (tests/test_mascot_contract.py) — она
// удалена вместе с пакетом `vector/` 15.08.2026. Это НЕ ослабление: питоновская копия
// в продукте не исполнялась, а живой код — здесь. Контракт стал спецификацией, а не
// сверкой двух реализаций, и этот тест теперь единственный, кто её держит.
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
