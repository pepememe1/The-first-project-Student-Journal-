// messagePreviewKinds.test.mjs — каждый вид сообщения, который лента рисует отдельно,
// известен и превью в списке чатов (23.10.2026).
//
// Живой прогон: в списке чатов стояло «Вы: act:dd54fbe…». Опрос пишется видом `poll`, в его
// теле лежит только id, а превью знало `activity` и `board`, но не `poll`, и отдавало тело
// как текст. Новый вид сообщения с id в теле повторил бы то же самое, поэтому проверяется
// свойство: виды из ленты (ChatThread.vue) ⊆ виды, разобранные в messagePreview.js.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

function kindsIn(src) {
  return new Set([...src.matchAll(/msg\.kind === '([a-z_]+)'/g)].map((m) => m[1]))
}

const FEED = read('../src/components/messenger/ChatThread.vue')
const PREVIEW = read('../src/utils/messagePreview.js')

function missingInPreview(feedSrc, previewSrc) {
  const preview = kindsIn(previewSrc)
  return [...kindsIn(feedSrc)].filter((k) => !preview.has(k))
}

test('превью знает каждый вид сообщения, который лента рисует отдельно', () => {
  assert.ok(kindsIn(FEED).size >= 6, `в ленте нашлось только ${kindsIn(FEED).size} видов — разбор ослеп`)
  assert.deepEqual(missingInPreview(FEED, PREVIEW), [],
    'виды сообщений без превью: в списке чатов будет тело как есть')
})

test('обратный ход: без ветки опроса проверка находит пропуск', () => {
  const broken = PREVIEW.replace(" || msg.kind === 'poll'", '')
  assert.notEqual(broken, PREVIEW)
  assert.deepEqual(missingInPreview(FEED, broken), ['poll'])
})
