/**
 * loginHints.test.mjs — вход для человека, который «с компьютером на вы» (13.10.2026).
 *
 * ━━ ЧТО ДЕРЖИМ ━━
 * 1. Клавиатура телефона не портит логин: у полей стоят `autocapitalize="none"`,
 *    `autocorrect="off"`, `spellcheck="false"`. Без них телефон сам делает первую букву
 *    заглавной, логин различает регистр — и верно набранный логин отвергался.
 * 2. После отказа «неверный логин или пароль» форма называет, ЧТО проверить: Caps Lock,
 *    язык клавиатуры, пробел. Правила — чистая функция, проверяется поведением.
 * 3. Кнопка помощи подписана словами и не закрывается тем же касанием, что её открыло.
 * 4. Очки «для слабовидящих» стоят на экране входа, а не только в кабинете.
 *
 * ⚠️ ОБРАТНЫЙ ХОД: `seesTheDefect` ниже прогоняет те же проверки по прежней разметке
 * поля (без атрибутов) и по прежнему обработчику нажатия — обе обязаны её отвергнуть.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { loginHints, capsLockState } from '../src/utils/loginHints.js'

const read = (rel) => readFileSync(
  new URL(rel, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), 'utf8')
const page = read('../src/pages/LoginPage.vue')
const code = page.replace(/<!--[\s\S]*?-->/g, '')

/** Открывающий тег поля ввода с данным id. */
function inputTag(src, id) {
  const m = src.match(new RegExp(`<input[^>]*\\bid="${id}"[^>]*>`))
  return m ? m[0] : ''
}
function keyboardLeavesItAlone(tag) {
  return /autocapitalize="none"/.test(tag) && /autocorrect="off"/.test(tag) && /spellcheck="false"/.test(tag)
}

test('клавиатура телефона не «исправляет» ни логин, ни показанный пароль', () => {
  for (const id of ['login', 'password']) {
    const tag = inputTag(code, id)
    assert.ok(tag, `нет поля #${id}`)
    assert.ok(keyboardLeavesItAlone(tag), `поле #${id}: телефон поставит заглавную букву или «исправит» слово`)
  }
})

test('обратный ход: прежнее поле логина проверку не проходит', () => {
  const old = '<input v-model="login" id="login" name="username" autocomplete="username" class="h-11">'
  assert.equal(keyboardLeavesItAlone(inputTag(old, 'login')), false)
})

test('подписи связаны с полями: нажатие на слово «Пароль» ставит курсор в поле', () => {
  assert.match(code, /<label for="login"/)
  assert.match(code, /<label for="password"/)
})

test('после отказа названо, что проверить', () => {
  assert.deepEqual(loginHints({ login: 'ivanov', password: 'Secret1' }), [])
  assert.deepEqual(loginHints({ login: 'ivanov', password: 'x', capsLock: true }), ['caps'])
  assert.deepEqual(loginHints({ login: 'ivanov', password: 'зфыыцщкв' }), ['passwordCyrillic'])
  assert.deepEqual(loginHints({ login: 'шмфтщм', password: 'x' }), ['loginCyrillic'])
  assert.deepEqual(loginHints({ login: 'Ivanov', password: 'x' }), ['loginCapital'])
  assert.deepEqual(loginHints({ login: 'iva nov', password: 'x' }), ['loginSpace'])
  assert.deepEqual(loginHints({ login: 'ivanov', password: 'secret ' }), ['passwordSpace'])
})

test('подсказки не шумят: пробел по краям логина и Caps Lock не дают лишних строк', () => {
  // Края логина страница и так обрезает перед отправкой — говорить о них нечего.
  assert.deepEqual(loginHints({ login: '  ivanov ', password: 'x' }), [])
  // Заглавные при включённом Caps Lock уже объяснены первой строкой.
  assert.deepEqual(loginHints({ login: 'IVANOv', password: 'x', capsLock: true }), ['caps'])
  // Логин целиком заглавными без Caps Lock — так могли и выдать; молчим.
  assert.deepEqual(loginHints({ login: 'IVANOV', password: 'x' }), [])
})

test('Caps Lock узнаём из события клавиатуры, а где его нет — не гадаем', () => {
  assert.equal(capsLockState({ getModifierState: (k) => k === 'CapsLock' }), true)
  assert.equal(capsLockState({ getModifierState: () => false }), false)
  assert.equal(capsLockState({}), null)
  assert.equal(capsLockState(null), null)
})

test('страница показывает подсказки только при отказе по логину и паролю', () => {
  assert.match(code, /auth\.errorKind === 'credentials'/)
  assert.match(code, /v-for="h in hints"/)
  assert.match(code, /v-if="capsOn"/, 'Caps Lock должен быть виден сразу, до попытки входа')
  const store = read('../src/stores/auth.js')
  assert.match(store, /status === 401\) \{[^}]*errorKind\.value = 'credentials'/,
    'стор не помечает отказ 401 — подсказки не появятся никогда')
  assert.match(store, /errorKind\.value = ''/, 'признак отказа не сбрасывается перед новой попыткой')
})

/** Обработчик нажатия закрывает подсказку, которую только что открыл фокус того же касания? */
function closesOnTheSameTap(handler) {
  return /showLoginHelp \? closeLoginHelp\(\) : openLoginHelp\(\)/.test(handler)
}

test('кнопка помощи подписана и не гаснет от того же касания, что её открыло', () => {
  const at = code.indexOf('login.helpAria')
  const btn = code.slice(at - 600, at + 500)
  assert.match(btn, /login\.helpButton/, 'кнопка помощи снова без подписи — букву «i» не находят')
  assert.match(btn, /@click="toggleLoginHelp"/)
  assert.equal(closesOnTheSameTap(btn), false)
  assert.match(code, /Date\.now\(\) - helpOpenedAt > HELP_SAME_GESTURE_MS/)
  // обратный ход: прежний обработчик проверка узнаёт
  assert.equal(closesOnTheSameTap('@click="showLoginHelp ? closeLoginHelp() : openLoginHelp()"'), true)
})

test('укрупнить шрифт можно до входа', () => {
  assert.match(code, /<AccessibilityMenu\b/, 'очки «для слабовидящих» пропали с экрана входа')
})
