// pinchZoom.test.mjs — сайт можно увеличить щипком (WCAG 1.4.4, аудит 27.10.2026).
//
// Масштаб запрещали из-за автоприближения браузера к полю ввода с шрифтом мельче 16 px.
// Причину сняли правилом в style.css; запрет масштаба возвращаться не должен, а правило —
// исчезать (без него вернётся прыжок экрана при фокусе в поле).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('index.html не запрещает масштаб', () => {
  const v = read('../index.html').match(/<meta\s+name="viewport"\s+content="([^"]*)"/)?.[1] || ''
  assert.ok(v, 'мета viewport не найдена')
  assert.doesNotMatch(v, /user-scalable\s*=\s*no/)
  assert.doesNotMatch(v, /maximum-scale\s*=\s*1(\.0)?\b/)
})

test('на сенсорном экране поля ввода не мельче 16 px', () => {
  const css = read('../src/style.css')
  assert.match(css, /@media \(pointer: coarse\)\s*\{\s*input[^{]*textarea, select\s*\{\s*font-size: max\(16px, 1rem\)/)
})
