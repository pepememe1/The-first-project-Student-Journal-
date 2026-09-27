// adminMessengerStates.test.mjs — экран модерации не выдаёт сбой за «всё чисто»
// (аудит 22.09.2026: F-15, F-16, F-19, F-20; интерфейс F-11/F-12).
//
// Проверяется ИСХОДНИК экрана: браузера в прогоне нет, а каждое из свойств ниже — это
// ровно одна строка разметки или кода, которую легко вернуть случайно.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `catch { reports.value = [] }` — краснеет F-15; вернуть
// общий `<template v-else>` у обращений — F-16; `statusFilter` в загрузке профилей — F-20;
// убрать `focus-visible:opacity-100` у кнопки удаления — F-19.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../src/pages/admin/AdminMessenger.vue', import.meta.url), 'utf8')
const tpl = src.slice(src.indexOf('<template>'))

function fnBody(name) {
  const start = src.indexOf(`async function ${name}(`)
  assert.ok(start >= 0, `нет функции ${name}`)
  const next = src.indexOf('\nasync function ', start + 10)
  const nextPlain = src.indexOf('\nfunction ', start + 10)
  const ends = [next, nextPlain].filter((i) => i > 0)
  return src.slice(start, ends.length ? Math.min(...ends) : undefined)
}

test('F-15: сбой очереди жалоб — ошибка, а не «Жалоб нет»', () => {
  const body = fnBody('load')
  assert.match(body, /catch \(e\)[\s\S]*loadErrors\.value\.reports = /,
    'загрузка жалоб при ошибке молчит — экран покажет «Жалоб нет»')
  const err = tpl.indexOf('v-else-if="loadErrors.reports"')
  const empty = tpl.indexOf("adminMessenger.noReports")
  assert.ok(err > 0 && err < empty, 'ошибка обязана проверяться РАНЬШЕ пустого списка')
})

test('ошибка своя у каждой вкладки', () => {
  assert.doesNotMatch(src, /\bloadError\.value\b/, 'осталась общая ошибка на все вкладки')
  for (const v of ['reports', 'inbox', 'profiles', 'people']) {
    assert.ok(tpl.includes(`loadErrors.${v}`), `вкладка ${v} не показывает свою ошибку`)
  }
})

test('F-16: у каждой вкладки явная ветка, общего v-else нет', () => {
  for (const v of ['reports', 'inbox', 'profiles', 'people']) {
    assert.match(tpl, new RegExp(`v-(else-)?if="view === '${v}'"`), `нет ветки ${v}`)
  }
  assert.doesNotMatch(tpl, /<template v-else>\s*<div class="mb-4 flex items-center gap-2">\s*<button type="button" @click="loadInbox"/,
    'обращения снова под общим v-else — «Профили» и «Люди» нарисуют их под собой')
})

test('F-20: у профилей свой фильтр статуса и свой переключатель', () => {
  const body = fnBody('loadUserReports')
  assert.match(body, /profileStatusFilter\.value/, 'профили снова читают фильтр жалоб на сообщения')
  assert.doesNotMatch(body, /\bstatusFilter\.value/)
  assert.ok(tpl.includes('v-model="profileStatusFilter"'), 'фильтр профилей не виден на их вкладке')
})

test('F-19: кнопки удаления видны с клавиатуры и на тач-экране', () => {
  const buttons = [...tpl.matchAll(/<button[^>]*deleteMessage\(mm\)[^>]*>/g)].map((m) => m[0])
  assert.equal(buttons.length, 2)
  for (const b of buttons) {
    assert.match(b, /focus-visible:opacity-100/, 'кнопка удаления невидима при фокусе с клавиатуры')
    assert.match(b, /\[@media\(hover:none\)\]:opacity-100|pointer-coarse:opacity-100/,
      'кнопка удаления невидима на планшете (там нет наведения)')
    assert.match(b, /:aria-label=/, 'у кнопки удаления нет подписи для экранного диктора')
  }
})

test('F-11/F-12: «показаны не все» и подгрузка истории', () => {
  assert.ok(tpl.includes('reportsMeta.truncated') && tpl.includes('userReportsMeta.truncated')
    && tpl.includes('inboxMeta.truncated'), 'обрезанная очередь выглядит полной')
  assert.match(fnBody('loadEarlier'), /conversationMessages\(v\.conv, v\.reportId,\s*v\.nextBefore\)/,
    'история глубже первого окна недоступна модератору')
  assert.ok(tpl.includes('@click="loadEarlier"'), 'кнопки «Загрузить раньше» нет на экране')
})

test('удаление в просмотрщике правит ленту на месте, а не перечитывает её', () => {
  //Перечитывание шло без reportId (403 во вкладке «Жалобы», проглоченный) и мимо окна
  //истории (после «Загрузить раньше» пропадало окно) — второй заход Полковника.
  const body = fnBody('deleteMessage')
  assert.doesNotMatch(body, /conversationMessages\(/, 'удаление снова перечитывает переписку')
  assert.match(body, /mm\.deleted = true/)
  assert.match(body, /catch \(e\)[\s\S]*viewer\.value\.error = failText\(e\)/,
    'неудачное удаление снова молчит')
})
