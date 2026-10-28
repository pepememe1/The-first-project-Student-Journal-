// contactsReauth.test.mjs — правка почты и телефона идёт с текущим паролем (07.10.2026).
//
// Проверяет СЕРВЕР (`server/tests/test_contacts_reauth.py`); здесь — что страница вообще
// даёт ввести пароль и отправляет его. Без этого защита превратилась бы в глухую стену:
// сервер отвечает «введите текущий пароль», а ввести его негде. Это наш обычный дефект
// наизнанку — правило есть, а двери к нему нет.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { allDictText } from './_dict.mjs'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const card = read('../src/components/settings/ContactsCard.vue')
const api = read('../src/api/endpoints.js')
const dict = allDictText()

function body(name) {
  const m = card.match(new RegExp(`async function ${name}\\(\\) \\{([\\s\\S]*?)\\n\\}`))
  assert.ok(m, `в карточке контактов нет функции ${name}`)
  return m[1]
}

test('все три правки контактов отправляют текущий пароль', () => {
  assert.match(api, /setPhone: \(phone, current, code = ''\) =>\s*api\.post\('\/me\/contacts\/phone', \{ phone, current, code \}\)/)
  assert.match(api, /emailStart: \(email, current, code = ''\) =>\s*api\.post\('\/me\/contacts\/email\/start', \{ email, current, code \}\)/)
  //Удаление — POST с телом: пароль в теле, а тело у DELETE по дороге теряют.
  assert.match(api, /emailRemove: \(current, code = ''\) =>\s*api\.post\('\/me\/contacts\/email\/remove', \{ current, code \}\)/)
  assert.doesNotMatch(api, /api\.delete\('\/me\/contacts\/email'\)/, 'удаление почты снова уходит без пароля')
})

test('каждое действие сначала спрашивает пароль, отправляет его и потом стирает', () => {
  for (const [name, call] of [
    ['sendCode', /accountApi\.emailStart\(email\.value\.trim\(\), current\.value, mfaCode\.value\.trim\(\)\)/],
    ['removeEmail', /accountApi\.emailRemove\(current\.value, mfaCode\.value\.trim\(\)\)/],
    ['savePhone', /accountApi\.setPhone\(phone\.value\.trim\(\), current\.value, mfaCode\.value\.trim\(\)\)/],
  ]) {
    const src = body(name)
    assert.ok(src.trimStart().startsWith('if (!havePassword()) return'),
      `${name}: запрос уходит, не проверив, что пароль введён`)
    assert.match(src, call, `${name}: пароль не доезжает до запроса`)
    assert.match(src, /forgetPassword\(\)/, `${name}: пароль остаётся в поле после удачного действия`)
    assert.match(src, /explain\(e, /, `${name}: отказ сервера человеку не показан`)
  }
})

test('у пароля есть поле, а у второго фактора — своё, по требованию сервера', () => {
  assert.match(card, /<input id="contacts-current-password" ref="currentInput" v-model="current" type="password" autocomplete="current-password"/)
  assert.match(card, /<label for="contacts-current-password"/, 'у поля пароля нет подписи')
  assert.match(card, /x-gb-reason'\] === 'mfa_required'\) needMfa\.value = true/)
  assert.match(card, /<div v-if="needMfa"[\s\S]{0,400}v-model="mfaCode"/)
  //Вставку из менеджера паролей не запрещаем (ASVS V6.2.7) и автозаполнение не глушим.
  assert.doesNotMatch(card, /@paste\.prevent|autocomplete="off"/)
})

test('ни одно поле пароля в продукте не запрещает вставку и не глушит менеджер паролей', () => {
  //OWASP ASVS V6.2.6 и V6.2.7 — по ВСЕМ страницам, а не только по этой карточке.
  const SRC = fileURLToPath(new URL('../src', import.meta.url))
  const vue = readdirSync(SRC, { recursive: true }).filter((f) => String(f).endsWith('.vue'))
  assert.ok(vue.length > 100, `компонентов найдено ${vue.length} — обход ослеп`)
  let passwordFields = 0
  let serviceKeys = 0
  for (const rel of vue) {
    const text = readFileSync(join(SRC, String(rel)), 'utf8')
    assert.doesNotMatch(text, /@paste\.prevent|@paste="\$event\.preventDefault/, `${rel}: вставка запрещена`)
    for (const tag of text.match(/<input\b[^>]*>/g) || []) {
      const secret = /type="password"|'password'/.test(tag)
      const named = /v-model="[^"]*(password|pass\b|current|newPass|repeat)/i.test(tag) && /autocomplete="(current|new)-password"/.test(tag)
      if (!secret && !named) continue
      //Ключ внешнего сервиса (GigaChat) скрыт как пароль, но паролем человека не является:
      //автозаполнение у него выключено НАМЕРЕННО — иначе браузер подставит в поле ключа
      //собственный пароль администратора, и тот уедет в настройки как «ключ».
      if (/v-model="[^"]*(credentials|api_?key|secret)/i.test(tag)) { serviceKeys += 1; continue }
      passwordFields += 1
      assert.ok(secret, `${rel}: поле пароля показывает ввод открытым текстом: ${tag.slice(0, 90)}`)
      assert.doesNotMatch(tag, /autocomplete="off"/, `${rel}: менеджеру паролей запрещено заполнять поле`)
    }
  }
  assert.ok(passwordFields >= 5, `полей пароля найдено ${passwordFields} — проверка ослепла`)
  assert.ok(serviceKeys <= 2, `исключений «ключ сервиса» стало ${serviceKeys} — под него прячут пароли?`)
})

test('тексты есть на всех трёх языках', () => {
  for (const key of ['account.passwordNeeded', 'account.contactsPasswordHint', 'account.emailRemoveFailed']) {
    const n = dict.split(`'${key}':`).length - 1
    assert.equal(n, 3, `${key}: записей в словаре ${n}, а языков три`)
  }
})
