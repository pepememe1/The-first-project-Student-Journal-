// emojiFont.test.mjs — шрифт эмодзи качается только ради эмодзи (28.10.2026).
//
// Twemoji.woff2 весит 466 КБ, и браузер качает его, как только на экране появился любой
// знак из unicode-range, даже если глифа для него в шрифте нет. Широкий диапазон U+2600-27BF
// тянул шрифт в каждый журнал ради отметки «✓», а флаг выбора языка — на экран входа.
// Сторож держит правило, а не список: вне блока 1F000-1FAFF каждый знак диапазона обязан
// быть эмодзи по Unicode (Emoji) или служебным знаком сборки эмодзи (Emoji_Component).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readSource } from './_readSource.mjs'

const css = readSource('style.css')
const face = css.match(/@font-face\s*\{[^}]*font-family:\s*'GB Emoji'[^}]*\}/)?.[0] || ''
const ranges = (face.match(/unicode-range:([^;]+);/)?.[1] || '')
  .split(',')
  .map((s) => s.trim().replace(/^U\+/i, ''))
  .filter(Boolean)
  .map((s) => s.split('-').map((h) => parseInt(h, 16)))
  .map(([a, b = a]) => [a, b])

const covers = (ch) => ranges.some(([a, b]) => ch.codePointAt(0) >= a && ch.codePointAt(0) <= b)

// В этом блоке только пиктограммы; знаков, которые интерфейс пишет текстом, там нет.
const PICTOGRAPH_BLOCK = [0x1f000, 0x1faff]

test('у GB Emoji есть unicode-range', () => {
  assert.ok(face, 'в style.css нет @font-face для GB Emoji')
  assert.ok(ranges.length > 0, 'без unicode-range шрифт эмодзи качается на каждой странице')
})

test('вне блока пиктограмм диапазон — только эмодзи', () => {
  const stray = []
  for (const [a, b] of ranges) {
    if (a >= PICTOGRAPH_BLOCK[0] && b <= PICTOGRAPH_BLOCK[1]) continue
    for (let cp = a; cp <= b; cp++) {
      const ch = String.fromCodePoint(cp)
      if (!/[\p{Emoji}\p{Emoji_Component}]/u.test(ch)) stray.push(`U+${cp.toString(16).toUpperCase()}`)
    }
  }
  assert.deepEqual(stray.slice(0, 10), [], 'эти знаки не эмодзи, но тянут 466 КБ шрифта')
})

test('прогрев шрифта просит то самое семейство и знак из его диапазона', () => {
  //Опечатка в имени семейства или знак вне unicode-range — и document.fonts.load молча
  //ничего не загрузит: эмодзи после входа снова мигнут системными.
  const warm = readSource('utils/fontWarmup.js')
  const m = warm.match(/fonts\.load\('1em "([^"]+)"', '\\u\{([0-9A-Fa-f]+)\}'\)/)
  assert.ok(m, 'в fontWarmup.js нет вызова fonts.load')
  assert.equal(m[1], 'GB Emoji')
  assert.ok(face.includes(`font-family: '${m[1]}'`), 'семейство прогрева не совпадает с @font-face')
  assert.equal(covers(String.fromCodePoint(parseInt(m[2], 16))), true, 'знак прогрева вне unicode-range')
})

test('отметки журнала, звёзды и стрелки рисуются без шрифта эмодзи', () => {
  for (const ch of ['✓', 'Н', 'Б', 'О', '5', '★', '☆', '✗', '→', '➜', '©']) {
    assert.equal(covers(ch), false, `«${ch}» не должен тянуть шрифт эмодзи`)
  }
  //Обратная сторона: настоящие эмодзи шрифт рисует.
  for (const ch of ['😀', '✅', '⭐', '❤', '☀']) assert.equal(covers(ch), true, `«${ch}» — эмодзи`)
})
