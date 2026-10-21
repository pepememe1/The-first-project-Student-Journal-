// Подсказка свободных аудиторий при замене пары (21.10.2026): у ручки сервера обязан быть
// вызывающий, а у поля «Аудитория» — список подсказок. Иначе это наш класс «обещание без
// вызывающего»: сервер считает, а человек ничего не видит.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/pages/admin/AdminSchedule.vue', import.meta.url), 'utf8')
const api = readFileSync(new URL('../src/api/endpoints.js', import.meta.url), 'utf8')

test('редактор расписания зовёт подсказку свободных аудиторий и показывает её в поле', () => {
  assert.match(api, /freeRooms: \(params\) => api\.get\('\/web\/admin\/schedule\/free-rooms'/)
  assert.match(page, /adminApi\.freeRooms\(/, 'ручку никто не зовёт')
  assert.match(page, /list="gb-free-rooms"/, 'у поля «Аудитория» нет списка подсказок')
  assert.match(page, /<datalist id="gb-free-rooms">/)
})
