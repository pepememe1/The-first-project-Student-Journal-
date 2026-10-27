// paletteContrast.test.mjs — текст читается в любой из 16 палитр и обоих режимах (WCAG 4.5).
//
// Аудит 27.10.2026: серый подписей давал 3.2–3.6, янтарь среднего в журнале — 2.8,
// бирюза текстом в тёмной теме — 3.3, а «Тёмно-синий» — 1.9. Проверяется свойство по
// всем пресетам, а не список поправленных цветов: новый пресет или сдвиг нейтралей,
// уронивший контраст, покраснеет сам.
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildPalette, PRESETS, contrast } from '../src/theme/palette.js'

const MIN = 4.5
const surfaces = (p) => ({ bg: p.bg, bg2: p.bg2, card: p.card, card2: p.card2 })

function check(key, mode, onlyCard = false) {
  const bad = []
  for (const preset of PRESETS) {
    const p = buildPalette({ id: preset.id, mode })
    const s = onlyCard ? { card: p.card } : surfaces(p)
    for (const [name, bg] of Object.entries(s)) {
      const r = contrast(p[key], bg)
      if (r < MIN) bad.push(`${mode}/${preset.id}: ${key} на ${name} = ${r.toFixed(2)}`)
    }
  }
  return bad
}

for (const mode of ['light', 'dark']) {
  test(`${mode}: основной и приглушённый текст`, () => {
    assert.deepEqual([...check('text', mode), ...check('text3', mode), ...check('text2', mode)], [])
  })
  test(`${mode}: акцент текстом (accent_text)`, () => {
    assert.deepEqual(check('accent_text', mode), [])
  })
  test(`${mode}: красный, оранжевый, жёлтый текстом на карточке`, () => {
    assert.deepEqual([...check('red', mode, true), ...check('orange', mode, true), ...check('yellow', mode, true)], [])
  })
}

test('акцент для текста — тот же оттенок, а не замена цветом', () => {
  // Сдвиг только к белому или чёрному: «Розовый» не должен стать бирюзовым.
  const p = buildPalette({ id: 'pink', mode: 'dark' })
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(p.accent_text.slice(i, i + 2), 16))
  assert.ok(r > g && r > b, `ожидался розоватый, получилось ${p.accent_text}`)
})
