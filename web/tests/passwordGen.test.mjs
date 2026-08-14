// Генератор паролей админки. Проверяем не «случайность» (её не проверить), а ПОЛИТИКУ:
// длину, обязательные классы символов и совпадение алфавита с серверным близнецом.
//
// ⚠️ Последняя проверка — главная. `server/app/reg_utils.py::gen_password` выдаёт пароль
// при одобрении заявки на регистрацию, здешний — по кнопке в админке. Разъезд алфавитов
// не ломает вход и не роняет тесты: он просто даёт два сорта паролей, и заметит это
// человек, а не программа. Поэтому набор спецсимволов читается ПРЯМО ИЗ .py-файла —
// правка там без правки здесь красит этот тест.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { generatePassword, PASSWORD_LENGTH, PASSWORD_ALPHABET } from '../src/utils/passwordGen.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')

const RUNS = 500          // классы гарантированы конструкцией, но пусть отвечает за серию

test('длина по умолчанию — 10 символов', () => {
  for (let i = 0; i < RUNS; i++) assert.equal(generatePassword().length, 10)
  assert.equal(PASSWORD_LENGTH, 10)
})

test('в каждом пароле есть строчная, заглавная, цифра и спецсимвол', () => {
  for (let i = 0; i < RUNS; i++) {
    const pw = generatePassword()
    assert.match(pw, /[a-z]/, `нет строчной: ${pw}`)
    assert.match(pw, /[A-Z]/, `нет заглавной: ${pw}`)
    assert.match(pw, /[0-9]/, `нет цифры: ${pw}`)
    assert.match(pw, /[!@#$%^&*]/, `нет спецсимвола: ${pw}`)
  }
})

test('символов вне разрешённого алфавита не бывает', () => {
  for (let i = 0; i < RUNS; i++) {
    for (const ch of generatePassword()) {
      assert.ok(PASSWORD_ALPHABET.includes(ch), `посторонний символ ${JSON.stringify(ch)}`)
    }
  }
})

test('короче 8 символов не выдаётся — как и на сервере', () => {
  // Сервер делает `length = max(8, length)`; повторяем, иначе вызов с 4 дал бы пароль,
  // который на другом пути продукта считается недопустимо коротким.
  assert.equal(generatePassword(4).length, 8)
  assert.equal(generatePassword(0).length, 8)
  assert.equal(generatePassword(16).length, 16)
})

test('позиция классов не предсказуема — перемешивание работает', () => {
  // Без Фишера—Йетса первые четыре символа всегда шли бы в порядке
  // «строчная, заглавная, цифра, спец», и по паролю читался бы генератор.
  const digitFirst = Array.from({ length: RUNS }, () => generatePassword())
    .filter((pw) => /[0-9]/.test(pw[0])).length
  assert.ok(digitFirst > 0, 'цифра ни разу не встала первой за 500 попыток — похоже, перемешивания нет')
})

test('набор спецсимволов совпадает с server/app/reg_utils.py', () => {
  const py = readFileSync(join(ROOT, 'server', 'app', 'reg_utils.py'), 'utf8')
  const m = py.match(/^_SPECIALS\s*=\s*"([^"]+)"/m)
  assert.ok(m, 'в reg_utils.py не нашёлся _SPECIALS — проверка ослепла, почини её')
  const pySpecials = [...m[1]].sort().join('')
  const jsSpecials = [...PASSWORD_ALPHABET].filter((c) => !/[a-zA-Z0-9]/.test(c)).sort().join('')
  assert.equal(jsSpecials, pySpecials,
    'алфавиты разошлись: пароли из админки и из заявок на регистрацию перестали быть одного сорта')
})
