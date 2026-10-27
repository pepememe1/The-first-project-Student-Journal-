// dialogDiscardGuard.test.mjs — щелчок мимо окна не теряет введённое молча (27.10.2026).
//
// Живой прогон с телефона: «Добавить преподавателя», набрано ФИО, тап у края окна —
// окно закрыто, данные потеряны. Защита живёт в директиве v-dialog одна на все окна:
// если человек вводил данные, щелчок по подложке (и Esc, и «назад») сначала спрашивает.
// Здесь — правило «что считается вводом»: поиск и фильтры не должны вызывать вопрос.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const { countsAsEntry } = await import('../src/directives/dialog.js')

function field(tag, attrs = {}, extra = {}) {
  return { tagName: tag.toUpperCase(), getAttribute: (n) => (n in attrs ? attrs[n] : null), ...extra }
}

test('поля формы — ввод, который жалко потерять', () => {
  assert.equal(countsAsEntry(field('input', { type: 'text', placeholder: 'Фамилия' })), true)
  assert.equal(countsAsEntry(field('input')), true)
  assert.equal(countsAsEntry(field('textarea', { placeholder: 'Тема занятия' })), true)
  assert.equal(countsAsEntry(field('select')), true)
  assert.equal(countsAsEntry(field('input', { type: 'checkbox' })), true)
  assert.equal(countsAsEntry(field('div', {}, { isContentEditable: true })), true)
})

test('поиск и служебные поля вопроса не вызывают', () => {
  assert.equal(countsAsEntry(field('input', { type: 'search' })), false)
  assert.equal(countsAsEntry(field('input', { placeholder: 'Поиск по ФИО' })), false)
  assert.equal(countsAsEntry(field('input', { 'aria-label': 'Найти человека' })), false)
  assert.equal(countsAsEntry(field('input', { role: 'combobox' })), false)
  assert.equal(countsAsEntry(field('input', { 'data-dialog-ignore': '' })), false)
  assert.equal(countsAsEntry(field('input', { type: 'hidden' })), false)
  assert.equal(countsAsEntry(field('button')), false)
  assert.equal(countsAsEntry(null), false)
})

test('директива вешает защиту и снимает её вместе с окном', () => {
  // Свойство кода директивы: обработчик перехвата ставится и убирается парой, иначе
  // закрытое окно продолжало бы держать слушатель.
  const src = readFileSync(new URL('../src/directives/dialog.js', import.meta.url), 'utf8')
  assert.match(src, /addEventListener\('click', st0\.onGuard, true\)/)
  assert.match(src, /removeEventListener\('click', st\.onGuard, true\)/)
  assert.match(src, /data-dialog-guard/)
})
