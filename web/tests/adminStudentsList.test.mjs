// adminStudentsList.test.mjs — админ → «Студенты» на большой базе и без портала.
//
// Живой прогон 01.10.2026 (520 студентов, 23 группы, портал недоступен):
//  • фильтр групп содержал ТОЛЬКО «Все группы» — список собирался после ответа портала;
//  • 520 строк одной простынёй (21 500 px, шесть тысяч узлов DOM);
//  • кнопка «Бакалавриат, специалитет» вела в вечное «Студентов нет».
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../src/pages/admin/AdminStudents.vue', import.meta.url), 'utf8')
  .replace(/\r\n/g, '\n')

/** Тело onMounted до закрывающей `})` в начале строки. */
function mountedBody(text) {
  const at = text.indexOf('onMounted(async () => {')
  assert.ok(at >= 0, 'нет onMounted')
  return text.slice(at, text.indexOf('\n})', at))
}

/** Список групп заполняется ДО первого ожидания портала (await scheduleApi/loadCategories). */
function groupsBeforePortal(text) {
  const body = mountedBody(text)
  const fill = body.indexOf('groupChoices.value =')
  const portalWaits = [/await\s+scheduleApi\./, /await\s+loadCategories\(/]
    .map((re) => body.search(re)).filter((i) => i >= 0)
  return fill >= 0 && portalWaits.every((i) => i > fill)
}

test('группы из базы попадают в фильтр, не дожидаясь портала', () => {
  assert.ok(groupsBeforePortal(src), 'фильтр групп снова ждёт портал')
})

test('обратный ход: прежний порядок (портал до списка групп) проверка ловит', () => {
  const broken = src.replace('onMounted(async () => {\n  await reload()',
    'onMounted(async () => {\n  await reload()\n  await loadCategories()')
  assert.notEqual(broken, src)
  assert.ok(!groupsBeforePortal(broken))
})

test('таблица рисует страницу, а не весь список', () => {
  assert.match(src, /v-for="\(r, i\) in pageRows"/, 'таблица снова рисует все строки')
  assert.match(src, /const PAGE = \d+/)
  assert.match(src, /rows\.value\.slice\(page\.value \* PAGE/)
})

test('кнопки категорий — только непустые', () => {
  assert.match(src, /v-for="c in visibleCategories"/)
})
