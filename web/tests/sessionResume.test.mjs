/**
 * sessionResume.test.mjs — конец сессии объяснён, и человек возвращается туда, где был
 * (13.10.2026).
 *
 * Было: сессия (пять часов) кончалась — журнал молча показывал форму входа, а после входа
 * открывал главную. Преподаватель посреди выставления оценок видел это как поломку.
 *
 * ⚠️ ОБРАТНЫЙ ХОД: «следующий за общим компьютером» — отдельный тест; убери сверку
 * отпечатка в `takeResume`, и он краснеет (чужой человек получает чужой адрес).
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { rememberResume, takeResume, dropResume, fingerprint, RESUME_MAX_AGE_MS }
  from '../src/utils/sessionResume.js'

/** Хранилище вкладки для теста. */
function box() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: (k) => { m.delete(k) },
    get size() { return m.size },
    dump: () => [...m.values()].join(' '),
  }
}

test('тот же человек возвращается на ту же страницу', () => {
  const store = box()
  assert.equal(rememberResume('semenova', '/teacher/journal?group=K74', { store, now: 1000 }), true)
  assert.equal(takeResume('semenova', { store, now: 2000 }), '/teacher/journal?group=K74')
})

test('следующий за общим компьютером на чужую страницу не попадает', () => {
  const store = box()
  rememberResume('semenova', '/teacher/journal?group=K74', { store, now: 1000 })
  assert.equal(takeResume('orlov', { store, now: 2000 }), '')
  // И запись при этом стёрта: вошедший третьим первый человек её уже не получит.
  assert.equal(takeResume('semenova', { store, now: 3000 }), '')
})

test('адрес отдаётся один раз', () => {
  const store = box()
  rememberResume('semenova', '/teacher/stats', { store, now: 1000 })
  assert.equal(takeResume('semenova', { store, now: 2000 }), '/teacher/stats')
  assert.equal(takeResume('semenova', { store, now: 2001 }), '')
})

test('старый адрес не возвращается', () => {
  const store = box()
  rememberResume('semenova', '/teacher/stats', { store, now: 0 })
  assert.equal(takeResume('semenova', { store, now: RESUME_MAX_AGE_MS + 1 }), '')
})

test('возвращать некуда: вход, промах по адресу, чужой сайт, пустой логин', () => {
  const store = box()
  for (const bad of ['/login', '/login?redirect=/x', '/404?from=/x', '/', '//evil.example', 'https://evil.example', '']) {
    assert.equal(rememberResume('semenova', bad, { store }), false, `запомнили «${bad}»`)
  }
  assert.equal(rememberResume('', '/teacher/stats', { store }), false)
  assert.equal(store.size, 0)
})

test('в хранилище вкладки лежит отпечаток, а не логин', () => {
  const store = box()
  rememberResume('ivanov@example.com', '/student', { store, now: 1 })
  assert.ok(!store.dump().includes('ivanov'), 'логин (он же почта) остался в хранилище после конца сессии')
  assert.notEqual(fingerprint('semenova'), fingerprint('orlov'))
  assert.equal(fingerprint(' semenova '), fingerprint('semenova'))
})

test('вышел сам — возвращать некуда', () => {
  const store = box()
  rememberResume('semenova', '/teacher/stats', { store, now: 1 })
  dropResume({ store })
  assert.equal(takeResume('semenova', { store, now: 2 }), '')
})

test('хранилище недоступно — вход от этого не страдает', () => {
  const broken = {
    getItem() { throw new Error('denied') },
    setItem() { throw new Error('denied') },
    removeItem() { throw new Error('denied') },
  }
  assert.equal(rememberResume('semenova', '/teacher/stats', { store: broken }), false)
  assert.equal(takeResume('semenova', { store: broken }), '')
  assert.doesNotThrow(() => dropResume({ store: broken }))
})

test('проводка: причина названа на форме входа, адрес запомнен ДО очистки сессии', () => {
  const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
  const app = read('../src/App.vue')
  const remember = app.indexOf('rememberResume(auth.user?.login, at.fullPath)')
  const clear = app.indexOf('auth.clearSession()')
  assert.ok(remember > 0, 'конец сессии больше не запоминает, где был человек')
  assert.ok(remember < clear, 'адрес запоминается ПОСЛЕ очистки — логина уже нет, отличить людей нечем')
  assert.match(app, /auth\.setNotice\(reason\)/)
  assert.match(app, /setAuthExpiredHandler\(\(\) => toLogin\('expired'\)\)/)
  assert.match(app, /setOfflineExpiredHandler\(\(\) => toLogin\('offline'\)\)/)

  const login = read('../src/pages/LoginPage.vue')
  assert.match(login, /takeResume\(user\.login\)/)
  assert.match(login, /login\.noticeExpired/)
  assert.match(login, /login\.noticeOffline/)

  const store = read('../src/stores/auth.js')
  assert.match(store, /dropResume\(\)/, 'выход из аккаунта не стирает адрес возврата')
  assert.match(store, /notice\.value = ''\s+\/\/человек вошёл/, 'причина остаётся на форме после входа')
})
