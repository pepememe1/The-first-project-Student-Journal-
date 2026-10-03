// liveRunSmallFixes.test.mjs — мелкие находки живого прогона 01.10.2026.
//
// Каждая проверка смотрит на РЕШЕНИЕ в коде и имеет обратный ход на дословной строке
// дефекта: зелёная проверка, не умеющая покраснеть, хуже отсутствующей.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8').replace(/\r\n/g, '\n')

// ── «ср. 0.00» в Аттестации у студента без оценок (в журнале там «—») ──────────────────
const ZERO_AVG = /Number\(r\.average \|\| 0\)\.toFixed\(2\)/
test('Аттестация: «нет оценок» — «—», а не «ср. 0.00»', () => {
  const src = read('../src/pages/teacher/TeacherJournal.vue')
  assert.doesNotMatch(src, ZERO_AVG)
  assert.match(src, /Number\(r\.average\) > 0 \? Number\(r\.average\)\.toFixed\(2\) : '—'/)
})
test('обратный ход: прежняя строка с 0.00 находится', () => {
  assert.match("{{ Number(r.average || 0).toFixed(2) }}", ZERO_AVG)
})

// ── «через поискили создайте»: пробел в начале <span> выбрасывает сборщик Vue ──────────
const LOST_SPACE = /<span v-if="canCreate && tab === 'chats'"> \{\{/
test('мессенджер: пробел перед «или создайте» внутри выражения', () => {
  const src = read('../src/components/messenger/ChatList.vue')
  assert.doesNotMatch(src, LOST_SPACE)
  assert.match(src, /<span v-if="canCreate && tab === 'chats'">\{\{ ' ' \+/)
})
test('обратный ход: пробел-узел в начале span находится', () => {
  assert.match(`<span v-if="canCreate && tab === 'chats'"> {{ x }}</span>`, LOST_SPACE)
})

// ── Открыть канал из каталога = подписаться ─────────────────────────────────────────────
test('каталог каналов: подписка только с подтверждения', () => {
  const src = read('../src/components/messenger/ChatList.vue')
  assert.doesNotMatch(src, /@click="m\.joinChannel\(ch\.conversation_id\)"/)
  const fn = src.slice(src.indexOf('async function onCatalogChannel'))
  assert.ok(fn.indexOf('await confirm(') > 0 && fn.indexOf('await confirm(') < fn.indexOf('m.joinChannel('),
    'вступление в канал раньше вопроса')
})

// ── Пароль «••••••••» в пустом поле читался как заполненный ────────────────────────────
test('форма студента: подсказка пароля словами, не точками', () => {
  const src = read('../src/pages/admin/AdminStudents.vue')
  assert.doesNotMatch(src, /v-model="form\.password"[^>]*placeholder="••••••••"/)
})

// ── Плашки-заполнители документов распирали страницу (privacy 1649 px при окне 1440) ──
const NOWRAP_FILL = /\.fill\{[^}]*white-space:nowrap/
for (const doc of ['privacy.html', 'terms.html']) {
  test(`${doc}: плашка-заполнитель переносится`, () => {
    assert.doesNotMatch(read(`../public/${doc}`), NOWRAP_FILL)
  })
}
test('обратный ход: nowrap у .fill находится', () => {
  assert.match('.fill{background:x;\n padding:0;white-space:nowrap}', NOWRAP_FILL)
})

// ── Родитель с неподтверждённой привязкой видел «Не удалось получить статистику» ───────
test('обзор успеваемости показывает причину отказа 403 словами сервера', () => {
  const src = read('../src/components/vector/GradesOverview.vue')
  assert.match(src, /status === 403 && typeof e\.response\.data\?\.detail === 'string'/)
  assert.match(src, /\{\{ failReason \|\| locale\.t\('gradesOverview\.failed'/)
})

// ── Вектор: тайм-аут при живой сети — не «Работаю без интернета» ───────────────────────
test('Вектор различает тайм-аут сервера и отсутствие сети', () => {
  const src = read('../src/stores/vector.js')
  const branch = src.slice(src.indexOf('if (!e.response) {'))
  assert.match(branch.slice(0, 900), /e\?\.code === 'ECONNABORTED'/)
  assert.match(branch.slice(0, 900), /vectorPage\.slowMode/)
})
