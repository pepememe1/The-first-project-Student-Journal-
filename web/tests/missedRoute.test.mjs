// Правило «куда девать промахнувшегося» (решение Влада, 23.08.2026).
//
// Проверяем СВОЙСТВО, а не список адресов: список страниц меняется каждый заход, а
// правило — нет. Сломать его легко перестановкой двух условий, и сломается оно молча:
// человек просто окажется не там, где ожидал, и никто не поймёт, что это регрессия.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { decideMiss, ROLE_PREFIXES } from '../src/utils/missedRoute.js'

test('промах внутри своей роли — на главную', () => {
  assert.equal(decideMiss('/student/qwerty', 'student'), 'home')
  assert.equal(decideMiss('/admin/nope', 'admin'), 'home')
  assert.equal(decideMiss('/teacher/', 'teacher'), 'home')
})

test('чужая роль в адресе — 404', () => {
  assert.equal(decideMiss('/admin/students', 'student'), 'notFound')
  assert.equal(decideMiss('/student/journal', 'admin'), 'notFound')
  assert.equal(decideMiss('/parent/children', 'teacher'), 'notFound')
})

test('адрес без роли — тоже просто промах', () => {
  // «Вам сюда нельзя» там, где раздела нет ни для кого, было бы неправдой.
  for (const p of ['/qwerty', '/', '', '/favicon.ico']) {
    assert.equal(decideMiss(p, 'student'), 'home', p)
  }
})

test('правило одинаково для всех ролей', () => {
  for (const mine of ROLE_PREFIXES) {
    for (const other of ROLE_PREFIXES) {
      const got = decideMiss(`/${other}/whatever`, mine)
      assert.equal(got, mine === other ? 'home' : 'notFound', `${mine} → /${other}/`)
    }
  }
})
