// accountOwnership.test.mjs — учётка студента после выдачи пароля (27.10.2026, Влад).
//
// Порядок: выданный пароль → просьба привязать почту и сменить пароль → учётка
// принадлежит студенту (администратор не сбросит и не возьмёт в лист) → забытый пароль
// восстанавливается кодом из письма, кнопка появляется после ДВУХ неудачных входов.
// Сервер держит это сам (`server/tests/test_account_ownership.py`); здесь — что двери на
// экране существуют и ведут куда надо. Окно, которое никто не открывает, и кнопка,
// которая висит всегда, — оба наши частые дефекты.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readSource } from './_readSource.mjs'

const LOGIN = readSource('pages/LoginPage.vue')
const RECOVER = readSource('components/auth/PasswordRecoveryDialog.vue')
const ONBOARD = readSource('components/account/AccountOnboardingDialog.vue')
const SHELL = readSource('layouts/AppShell.vue')
const ROLLOUT = readSource('components/account/RolloutDialog.vue')
const EXTRA = readSource('components/account/AccountExtraPanel.vue')
const API = readSource('api/endpoints.js')

/** Кнопка «Забыли пароль?» появляется после N неудач. Разбор — тот же, что у страницы. */
function forgotThreshold(src) {
  const m = src.match(/const FORGOT_AFTER = (\d+)/)
  if (!m) return null
  const shown = /const showForgot = computed\(\(\) => failedLogins\.value >= FORGOT_AFTER/.test(src)
  const counted = /status === 401 && auth\.errorKind === 'credentials'\) failedLogins\.value \+= 1/.test(src)
  return shown && counted ? Number(m[1]) : null
}

test('«Забыли пароль?» — после двух неудачных входов, а не всегда', () => {
  assert.equal(forgotThreshold(LOGIN), 2)
  assert.match(LOGIN, /<button v-if="showForgot"[^>]*\n?[^>]*@click="openCodeRecover"/,
    'кнопка обязана стоять под showForgot')
  assert.match(LOGIN, /<PasswordRecoveryDialog v-if="showForgot && showCodeRecover"/,
    'окно рисуется только при открытой двери — подняли ref в обход, показывать нечего')
  const fn = LOGIN.slice(LOGIN.indexOf('function openCodeRecover('))
  assert.match(fn.slice(0, 120), /if \(!showForgot\.value\) return/, 'дверь отказывает первой строкой')
})

test('обратный ход: кнопка, висящая всегда, и счётчик без вызова находятся', () => {
  assert.equal(forgotThreshold(LOGIN.replace('const FORGOT_AFTER = 2', 'const FORGOT_AFTER = 0')), 0)
  assert.equal(forgotThreshold(LOGIN.replace('failedLogins.value += 1', 'void 0')), null,
    'счётчик, который никто не увеличивает, — обещание без вызывающего')
})

test('восстановление: код по логину и почте, пароль дважды, смена — прежней дверью', () => {
  assert.match(API, /recoverCodeStart: \(login, email\) => api\.post\('\/auth\/recover\/code\/start'/)
  assert.match(API, /recoverCodeVerify: \(login, code\) => api\.post\('\/auth\/recover\/code\/verify'/)
  assert.match(RECOVER, /authApi\.recoverCodeStart\(/)
  assert.match(RECOVER, /authApi\.recoverCodeVerify\(/)
  //Пароль меняет тот же `/auth/recover/confirm`, что у ссылки: второго пути записи нет.
  assert.match(RECOVER, /authApi\.recoverConfirm\(token\.value, next\.value/)
  assert.match(RECOVER, /next\.value === repeat\.value/, 'новый пароль обязан вводиться дважды')
  assert.match(RECOVER, /saveCredential\(/, 'новый пароль браузер обязан предложить сохранить')
  assert.match(RECOVER, /'mfa_required'\) needMfa\.value = true/, 'второй фактор — по признаку сервера')
})

test('первичная настройка: подключена к оболочке, почта → код → пароль дважды', () => {
  assert.match(SHELL, /<AccountOnboardingDialog v-if="!embed && auth\.role === 'student'"/)
  assert.match(ONBOARD, /accountApi\.onboarding\(\)/)
  assert.match(ONBOARD, /accountApi\.onboardingEmail\(/)
  assert.match(ONBOARD, /accountApi\.emailConfirm\(code\.value\)/, 'код — той же дверью, что в настройках')
  assert.match(ONBOARD, /accountApi\.onboardingPassword\(next\.value, repeat\.value/)
  assert.match(ONBOARD, /saveCredential\(login\.value, next\.value\)/)
  //«Позже» — до следующего входа, ключ — логин (общий компьютер колледжа).
  assert.match(ONBOARD, /postpone\(login\.value\)/)
  assert.doesNotMatch(ONBOARD, /localStorage/, '«Позже» навсегда сделало бы пароль из листа вечным')
})

test('учётка студента: галочка в листе погашена, сброс в редакторе спрятан', () => {
  assert.match(ROLLOUT, /const isOwned = \(s\) => s\.state === 'owned'/)
  assert.match(ROLLOUT, /:disabled="isOwned\(s\)"/)
  assert.match(ROLLOUT, /new Set\(pickable\(\)\.map/, '«отметить всех» не должно брать запертых')
  assert.match(EXTRA, /v-else-if="owned"/, 'при запертой учётке кнопки сброса нет')
  const ownedAt = EXTRA.indexOf('v-else-if="owned"')
  const resetAt = EXTRA.indexOf('@click="reset"', EXTRA.indexOf('v-else-if="cred"'))
  assert.ok(ownedAt > 0 && resetAt > ownedAt, 'ветка «учётка студента» обязана стоять ДО ветки со сбросом')
})
