// desktopLoginTimeout.test.mjs — первый вход в программе не обрывается 20-секундным пределом.
//
// Живой прогон 01.10.2026: первый вход админа на большой базе ждёт копию данных 27–59 с,
// а общий предел запроса (20 с) обрывал его «ошибкой соединения»; вторая попытка шла 5 с.
// Плюс: на 503 программа называет причину («данные не успели скачаться»), а окно входа
// показывало общую фразу «попробуйте через минуту».
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const endpoints = read('../src/api/endpoints.js')
const auth = read('../src/stores/auth.js')
const loginPage = read('../src/pages/LoginPage.vue')

/** Тело стрелочной функции `name:` в authApi — до следующего ключа объекта. */
function apiEntry(src, name) {
  const at = src.indexOf(`\n  ${name}: (`)
  assert.ok(at >= 0, `в authApi нет ${name}`)
  const next = src.indexOf('\n  ', at + 3)
  let end = next
  //Значение может переноситься на следующую строку с отступом в 4 пробела.
  while (src.startsWith('\n    ', end)) end = src.indexOf('\n  ', end + 5)
  return src.slice(at, end)
}

test('предел входа в программе — не меньше минуты', () => {
  const m = endpoints.match(/DESKTOP_LOGIN_TIMEOUT_MS\s*=\s*(\d+)/)
  assert.ok(m, 'нет DESKTOP_LOGIN_TIMEOUT_MS')
  assert.ok(Number(m[1]) >= 60000, `предел ${m[1]} мс короче первой закачки копии`)
  assert.match(endpoints, /isDesktopApp\(\)\s*\?\s*\{\s*timeout:\s*DESKTOP_LOGIN_TIMEOUT_MS\s*\}/,
    'увеличенный предел обязан действовать ТОЛЬКО в программе')
})

test('и вход, и второй шаг входа идут с этим пределом', () => {
  for (const name of ['login', 'mfaVerify']) {
    assert.match(apiEntry(endpoints, name), /loginOpts\(\)/, `${name} без loginOpts()`)
  }
})

test('на 5xx окно входа показывает причину, названную сервером', () => {
  const branch = auth.slice(auth.indexOf('else if (status >= 500)'))
  assert.match(branch.slice(0, 300), /e\.response\?\.data\?\.detail/,
    'причина из ответа 503 программы не доходит до человека')
})

test('долгий первый вход в программе объясняется подсказкой', () => {
  assert.match(loginPage, /slowLogin/)
  assert.match(loginPage, /login\.firstSyncHint/)
})

test('обратный ход: проверка видит вход без увеличенного предела', () => {
  const broken = endpoints.replace(
    "api.post('/auth/login', { login, password, ...extra }, loginOpts())",
    "api.post('/auth/login', { login, password, ...extra })")
  assert.notEqual(broken, endpoints, 'обратный ход не нашёл строку вызова')
  assert.doesNotMatch(apiEntry(broken, 'login'), /loginOpts\(\)/)
})
