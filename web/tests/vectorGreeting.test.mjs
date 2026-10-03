// vectorGreeting.test.mjs — первое сообщение Вектора по роли и по имени (28.09.2026).
//
// Жалоба Ярослава: приветствие было одно на всех («Привет! … спросите про средний балл»),
// администратору предлагались вопросы студента, а преподавателя Вектор не называл по имени.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { greetingKey, greetingName, namePart } from '../src/utils/vectorGreeting.js'
import { MESSAGES } from '../src/i18n/dictionaries.js'

const ROLES = ['student', 'teacher', 'admin', 'parent', 'moderator']

test('у каждой роли своё приветствие во всех трёх языках, и в нём есть место для имени', () => {
  for (const lang of ['ru', 'en', 'zh']) {
    const texts = ROLES.map((r) => MESSAGES[lang][greetingKey(r)])
    for (const [i, t] of texts.entries()) {
      assert.ok(t, `нет ${greetingKey(ROLES[i])} в ${lang}`)
      assert.ok(t.includes('{name}'), `${lang}/${ROLES[i]}: нет {name}`)
    }
    assert.equal(new Set(texts).size, ROLES.length, `${lang}: у ролей одинаковые приветствия`)
  }
  assert.equal(greetingKey('кто-то'), 'vectorGreet.student')
})

test('админу не предлагаются вопросы студента, студенту — «вы»', () => {
  const admin = MESSAGES.ru['vectorGreet.admin']
  assert.doesNotMatch(admin, /средний балл/, admin)
  assert.match(admin, /колледж/, admin)
  assert.match(MESSAGES.ru['vectorGreet.teacher'], /^Здравствуйте\{name\}!/)
  assert.match(MESSAGES.ru['vectorGreet.student'], /Спроси /)
})

test('имя берётся из ответа входа, а без него — из полного ФИО', () => {
  assert.equal(greetingName({ role: 'teacher', greet: 'Анна Петровна', name: 'x' }), 'Анна Петровна')
  //Сессия, открытая до обновления: поля greet нет.
  assert.equal(greetingName({ role: 'teacher', name: 'Семёнова Анна Петровна' }), 'Анна Петровна')
  assert.equal(greetingName({ role: 'student', name: 'Дашиева Арюна Баировна' }), 'Арюна')
  assert.equal(greetingName({ role: 'admin', name: 'Admin' }), '')
  assert.equal(greetingName(null), '')
})

test('без имени — «Здравствуйте!», а не «Здравствуйте, !»', () => {
  const t = MESSAGES.ru['vectorGreet.teacher']
  assert.match(t.replace('{name}', namePart('', 'ru')), /^Здравствуйте! /)
  assert.match(t.replace('{name}', namePart('Анна Петровна', 'ru')), /^Здравствуйте, Анна Петровна! /)
  assert.match(MESSAGES.zh['vectorGreet.teacher'].replace('{name}', namePart('Анна', 'zh')), /^您好，Анна！/)
})
