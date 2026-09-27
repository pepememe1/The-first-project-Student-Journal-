// deepLinks.test.mjs — присланная ссылка открывается у получателя, в том числе ПОСЛЕ входа
// (F-18 и второй заход Полковника, 26.09.2026).
//
// Проверяется ПОВЕДЕНИЕ правил (`utils/deepLinks.js`), а проводка — отдельно и коротко:
// прежний сторож сверял регуляркой текст компонентов и дефект «?peer= теряется при входе»
// пропустить мог по построению.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть в роутер `{ path: '/login', query: to.query }` —
// краснеет «не вошёл → вход с возвратом»; вернуть на вход `HOME_BY_ROLE[...]` — краснеет
// проводка; пропустить `//evil` в `safeRedirect` — краснеет открытое перенаправление.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { safeRedirect, afterLoginTarget, messagesRedirect, linkAction } from '../src/utils/deepLinks.js'

const HOME = { student: '/student', teacher: '/teacher' }

test('не вошёл → вход с адресом возврата, запрос не теряется', () => {
  const r = messagesRedirect(false, '', '/messages?peer=stud%3Abob', { peer: 'stud:bob' })
  assert.deepEqual(r, { path: '/login', query: { redirect: '/messages?peer=stud%3Abob' } })
})

test('вошёл → раздел сообщений СВОЕЙ роли с тем же запросом', () => {
  assert.deepEqual(messagesRedirect(true, 'teacher', '/messages?peer=x', { peer: 'x' }),
    { path: '/teacher/messages', query: { peer: 'x' } })
})

test('после входа — туда, куда вела ссылка', () => {
  assert.equal(afterLoginTarget('student', { redirect: '/messages?peer=x' }, HOME), '/messages?peer=x')
  assert.equal(afterLoginTarget('student', {}, HOME), '/student')
})

test('возврат только внутрь сайта: открытого перенаправления нет', () => {
  for (const bad of ['//evil.example/x', 'https://evil.example', '/\\evil.example', '/login?redirect=/x',
    '', null, 42]) {
    assert.equal(safeRedirect(bad), '', `пропустили наружу: ${bad}`)
  }
  assert.equal(safeRedirect('/teacher/journal?g=1'), '/teacher/journal?g=1')
})

test('запрос страницы сообщений: чат главнее человека', () => {
  assert.deepEqual(linkAction({ chat: 'c1', msg: '5', peer: 'p' }), { kind: 'chat', id: 'c1', msg: 5 })
  assert.deepEqual(linkAction({ peer: 'stud:bob' }), { kind: 'peer', id: 'stud:bob' })
  assert.equal(linkAction({}), null)
})

test('проводка: роутер, вход и страница сообщений зовут эти правила', () => {
  const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const login = readFileSync(new URL('../src/pages/LoginPage.vue', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/pages/MessengerPage.vue', import.meta.url), 'utf8')
  assert.match(router, /messagesRedirect\(auth\.isAuthenticated, auth\.role, to\.fullPath, to\.query\)/)
  assert.doesNotMatch(login, /router\.push\(HOME_BY_ROLE\[/, 'вход снова ведёт на главную мимо адреса возврата')
  assert.equal((login.match(/afterLoginTarget\(user\.role, route\.query, HOME_BY_ROLE\)/g) || []).length, 3,
    'не все три пути входа (пароль, ключ, второй фактор) уважают адрес возврата')
  assert.match(page, /linkAction\(route\.query\)/)
  assert.match(page, /watch\(\(\) => \[route\.query\.chat, route\.query\.peer\]/,
    'ссылка, открытая внутри сообщений, не сработает — страница не пересоздаётся')
})
