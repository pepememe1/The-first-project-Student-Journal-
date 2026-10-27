// logoutNotice.test.mjs — плашка «время работы без повторного входа вышло» не встречает
// человека, который вышел сам (23.10.2026, жалоба Ярослава: «на всех платформах»).
//
// Воспроизведено на телефоне: выход → перезапуск → на форме входа плашка «время вышло».
// Причина: на старте без входа приложение регистрировало пуш-токен, сервер отвечал 401,
// обновлять было нечего, и клиент звал «сессия истекла». Тот же путь у любого запроса
// без входа на сайте и в программе. Второй путь — окно самого выхода: notice гасился в
// начале `logout()`, а 401 мог прийти, пока выход ждал сервер.
// Компоненты и стор в node не поднять, поэтому проверяется проводка, у каждой проверки —
// обратный ход.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readText } from './_readSource.mjs'

//Через общую дверь: обратный ход ниже правит текст регуляркой с переводом строки, и на
//машине, где git выложил файлы с CRLF, он не срабатывал — тест краснел при исправном коде (27.10.2026).
const read = (rel) => readText(new URL(rel, import.meta.url))
const APP = read('../src/App.vue')
const AUTH = read('../src/stores/auth.js')
const MAIN = read('../src/main.js')

function explainsOnlyToWhoWasIn(src) {
  const body = src.slice(src.indexOf('function toLogin('), src.indexOf('onMounted('))
  const had = body.indexOf('const hadUser = !!auth.user')
  const clear = body.indexOf('auth.clearSession()')
  return had >= 0 && had < clear && /auth\.setNotice\(hadUser \? reason : ''\)/.test(body)
}

//Плашку и адрес возврата гасят после всех ожиданий сервера: 401, пришедший во время выхода,
//ставит плашку и запоминает страницу (ревью 23.10.2026 — про адрес возврата).
function logoutClearsNoticeLast(src) {
  const body = src.slice(src.indexOf('async function logout('), src.indexOf('function clearSession('))
  const lastAwait = body.lastIndexOf('await ')
  const lastNotice = body.lastIndexOf("notice.value = ''")
  const lastDrop = body.lastIndexOf('dropResume()')
  return lastNotice > body.lastIndexOf('user.value = null') && lastNotice > lastAwait
    && lastDrop > lastAwait
}

test('причину конца сессии объясняют только тому, кто был в системе', () => {
  assert.equal(explainsOnlyToWhoWasIn(APP), true)
})

test('обратный ход: безусловная плашка находится', () => {
  const broken = APP.replace("auth.setNotice(hadUser ? reason : '')", 'auth.setNotice(reason)')
  assert.notEqual(broken, APP)
  assert.equal(explainsOnlyToWhoWasIn(broken), false)
})

test('выход гасит плашку после всех ожиданий сервера', () => {
  assert.equal(logoutClearsNoticeLast(AUTH), true)
})

test('обратный ход: плашка, погашенная до ожиданий, находится', () => {
  const at = AUTH.indexOf('async function logout(')
  const end = AUTH.indexOf('function clearSession(')
  const body = AUTH.slice(at, end)
  //Как было до правки: плашка гасится в начале выхода, до ожиданий сервера.
  const early = body.replace(/\n(\s*)dropResume\(\)\n\s*notice\.value = ''/, '\n$1dropResume()')
    .replace('async function logout() {', "async function logout() {\n    notice.value = ''")
  assert.notEqual(early, body)
  assert.equal(logoutClearsNoticeLast(AUTH.slice(0, at) + early + AUTH.slice(end)), false)
  //И адрес возврата, стёртый до ожиданий.
  const earlyDrop = body.replace(/\n\s*dropResume\(\)/, '')
    .replace('async function logout() {', 'async function logout() {\n    dropResume()')
  assert.notEqual(earlyDrop, body)
  assert.equal(logoutClearsNoticeLast(AUTH.slice(0, at) + earlyDrop + AUTH.slice(end)), false)
})

test('без входа приложение не регистрирует пуш-токен на старте', () => {
  assert.match(MAIN, /if \(useAuthStore\(\)\.isAuthenticated\) await push\.registerToken\(\)/)
})
