// grading.contract.test.mjs — JS-сторона контракта кастомных шкал оценок (§ролей, 3.3.1).
//
// Прогоняет web/src/utils/grading.js по ТОМУ ЖЕ golden-файлу, что и Python
// (tests/test_grade_contract.py). Запуск: cd web && npm test
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { readdirSync, statSync } from 'node:fs'
import { toFivePoint, isFailedScaled, practiceAverage, groupAverage, markOfAverage, MARK_EDGES } from '../src/utils/grading.js'

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

// Отметка по среднему (28.10.2026): веб держал свою лесенку 4.5/3.5/3 в шести местах.
test('markOfAverage и MARK_EDGES совпадают с общим контрактом (Python↔JS)', () => {
  assert.deepEqual(MARK_EDGES, contract.mark_edges)
  for (const c of contract.mark_of_average) {
    assert.equal(markOfAverage(c.avg), c.expected, `markOfAverage(${c._case}) должно быть ${c.expected}`)
  }
})

test('своих границ 4.5/3.5/2.5 в интерфейсе нет — только markOfAverage', () => {
  const SRC = resolve(here, '../src')
  const walk = (dir, out = []) => {
    for (const n of readdirSync(dir)) {
      const p = resolve(dir, n)
      if (statSync(p).isDirectory()) { if (n !== 'i18n') walk(p, out) } else if (/\.(vue|js)$/.test(n)) out.push(p)
    }
    return out
  }
  const found = []
  for (const p of walk(SRC)) {
    if (p.replace(/\\/g, '/').endsWith('utils/grading.js')) continue
    readFileSync(p, 'utf-8').split('\n').forEach((line, i) => {
      if (/(>=|<=|<|>)\s*[234]\.5\b/.test(line)) found.push(`${p.slice(SRC.length + 1)}:${i + 1}`)
    })
  }
  assert.deepEqual(found, [], 'порог отметки по среднему — grading.js::markOfAverage (§4.44)')
})

test('журнал преподавателя не считает средний группы своей формулой', () => {
  const src = readFileSync(resolve(here, '../src/pages/teacher/TeacherJournal.vue'), 'utf-8')
  assert.match(src, /groupAverageOf\(/, 'средний группы обязан идти через grading.js::groupAverage')
  assert.doesNotMatch(src, /reduce\(\(a, b\) => a \+ b, 0\) \/ vals\.length\)\.toFixed/, 'вернулась своя формула')
})
