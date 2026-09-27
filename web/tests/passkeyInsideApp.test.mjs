// passkeyInsideApp.test.mjs — внутри программы нет двери, которая заведомо не откроется
// (N-04 аудита 22.09.2026).
//
// Ключ доступа (passkey) привязан к адресу сайта. Программа открывает ту же страницу с
// 127.0.0.1 — браузер не предложит ни одного ключа, а ключ, заведённый здесь, не подойдёт
// ни на сайте, ни в самой программе. Кнопки «Войти по ключу» и «Добавить это устройство»
// в программе были бы нерабочими, и человек решил бы, что сломан его ключ.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: снять `!insideApp` с кнопки входа — краснеет первый тест;
// показать «Добавить это устройство» в программе — краснеет второй.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')
const code = (s) => s.replace(/<!--[\s\S]*?-->/g, '').replace(/^\s*\/\/.*$/gm, '')

test('на экране входа программы нет кнопки входа по ключу', () => {
  const src = code(read('pages/LoginPage.vue'))
  const btn = src.slice(0, src.indexOf('@click="submitPasskey"'))
  const cond = btn.slice(btn.lastIndexOf('<div v-if="'))
  assert.match(cond, /!insideApp/, 'кнопка входа по ключу показывается внутри программы')
})

test('в настройках программы ключ не заводится, но список остаётся', () => {
  const src = code(read('pages/Settings.vue'))
  const card = src.slice(src.indexOf('id="set-biometric"'))
  const add = card.slice(0, card.indexOf('@click="addPasskey"'))
  assert.match(add, /<div v-else /, 'кнопка «Добавить это устройство» не спрятана в программе')
  assert.match(add, /<p v-if="insideApp"/, 'в программе нет пояснения, где завести ключ')
  assert.match(card.slice(0, 200), /v-if="canBiometric \|\| insideApp"/,
    'в программе пропал список ключей — удалить потерянный ключ стало негде')
  const fn = src.slice(src.indexOf('async function addPasskey() {'))
  assert.match(fn.slice(0, 80), /if \(insideApp\) return/, 'заведение ключа не заперто в программе')
})
