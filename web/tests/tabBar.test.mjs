// tabBar.test.mjs — вкладки разделов одного вида (28.10.2026).
//
// Было три вида: подчёркнутые, залитые таблетки и сегменты, и человек не узнавал в них
// одно действие. Теперь вкладки — только components/ui/TabBar.vue. Сторож ловит самодельную
// вкладку по её почерку: кнопка с подчёркиванием активной (-mb-px … border-b-2) или с
// заливкой, которая включается сравнением «tab/view/viewMode === …».
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readText } from './_readSource.mjs'

const SRC = fileURLToPath(new URL('../src/', import.meta.url))

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (name.endsWith('.vue')) out.push(full)
  }
  return out
}

const UNDERLINE = /-mb-px[^"]*border-b-2/
//section/course в листе логинов — фишки-фильтры «раздел → курс → группа», не вкладки.
const TAB_SWITCH = /:class="(?:tab|view|viewMode) === [^"]*(?:bg-accent text-white|bg-card text-text shadow|border-accent)/

test('самодельных вкладок нет — только TabBar', () => {
  const found = []
  for (const file of walk(SRC)) {
    if (file.replace(/\\/g, '/').endsWith('components/ui/TabBar.vue')) continue
    const text = readText(file)
    text.split('\n').forEach((line, i) => {
      if (UNDERLINE.test(line) || TAB_SWITCH.test(line)) found.push(`${file.slice(SRC.length)}:${i + 1}`)
    })
  }
  assert.deepEqual(found, [], 'вкладки разделов — через components/ui/TabBar.vue')
})

test('TabBar — настоящий tablist для диктора и клавиатуры', () => {
  const bar = readText(new URL('../src/components/ui/TabBar.vue', import.meta.url))
  assert.match(bar, /role="tablist"/)
  assert.match(bar, /role="tab"/)
  assert.match(bar, /:aria-selected=/)
  assert.match(bar, /ArrowRight/)
})
