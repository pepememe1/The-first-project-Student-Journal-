// vectorNlu.contract.test.mjs — JS-сторона контракта разбора вопроса к «Вектору».
//
// Прогоняет web/src/utils/vectorNlu.js::classify по ТОМУ ЖЕ golden-файлу, что и Python
// (tests/test_vector_intent_contract.py, источник правды — vector_nlu.py в корне репо).
// Файл сгенерирован tools/gen_vector_contract.py прогоном реального vector_nlu.classify —
// расхождение здесь значит, что мобильное приложение поймёт вопрос иначе, чем сайт/десктоп.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { classify, INTENT_STEMS } from '../src/utils/vectorNlu.js'

const here = dirname(fileURLToPath(import.meta.url))
const contract = JSON.parse(
  readFileSync(resolve(here, '../../docs/contracts/vector-intent-cases.json'), 'utf-8')
)
const cases = contract.cases

test('контракт не пуст и достаточно велик', () => {
  assert.ok(cases.length >= 60, 'случаев слишком мало для устойчивого контракта')
})

test('classify() совпадает с общим контрактом (Python↔JS) по ВСЕМ полям', () => {
  for (const c of cases) {
    const got = classify(c.q, c.surnames, c.subjects)
    assert.equal(got.intent, c.intent, `«${c.q}»: intent = ${got.intent}, ожидалось ${c.intent}`)
    assert.equal(
      got.surname,
      c.surname,
      `«${c.q}»: surname = ${JSON.stringify(got.surname)}, ожидалось ${JSON.stringify(c.surname)}`
    )
    assert.equal(
      got.subject,
      c.subject,
      `«${c.q}»: subject = ${JSON.stringify(got.subject)}, ожидалось ${JSON.stringify(c.subject)}`
    )
    assert.equal(
      got.day,
      c.day,
      `«${c.q}»: day = ${JSON.stringify(got.day)}, ожидалось ${JSON.stringify(c.day)}`
    )
  }
})

test('каждый интент лексикона достижим хотя бы одним случаем контракта', () => {
  const covered = new Set(cases.map((c) => c.intent))
  const missing = Object.keys(INTENT_STEMS).filter((intent) => !covered.has(intent))
  assert.deepEqual(missing, [], `интенты без единого случая: ${missing.join(', ')}`)
})

// 🔑 ОБРАТНЫЙ ТЕСТ — страховка от бессмысленного сторожа (тот же приём, что и в
// tests/test_vector_intent_contract.py::test_a_broken_lexicon_would_fail_the_contract).
// Если бы порт был сломан, сравнение с контрактом ОБЯЗАНО заметить расхождение —
// иначе тест выше зелёный при любой реализации. Портим НАСТОЯЩИЙ INTENT_STEMS (объект
// экспортирован как const, но его СОДЕРЖИМОЕ мутируемо — как и в Python-стороне, где
// ломается сам модуль, а не подставная копия) и обязательно восстанавливаем после.
test('намеренно сломанный лексикон проваливает контракт (иначе сторож бесполезен)', () => {
  const savedHello = INTENT_STEMS.hello
  const savedHomework = INTENT_STEMS.homework
  try {
    INTENT_STEMS.hello = [] // «привет»/«здравствуйте» больше не распознаются
    INTENT_STEMS.homework = [] // «что задали» — тоже

    let mismatches = 0
    for (const c of cases) {
      const got = classify(c.q, c.surnames, c.subjects)
      if (got.intent !== c.intent) mismatches += 1
    }
    assert.ok(mismatches > 0, 'испорченный лексикон прошёл бы контракт — сторож бесполезен')
  } finally {
    INTENT_STEMS.hello = savedHello
    INTENT_STEMS.homework = savedHomework
  }
})
