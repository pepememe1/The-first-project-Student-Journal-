// plural.test.mjs — форма слова по числу («502 подписчика», а не «502 подписчиков»).
//
// Живой прогон 01.10.2026: «502 подписчиков», «501 подписчиков». Формы задаются в
// словаре через «|», выбирают их правила языка (Intl.PluralRules).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { pickPlural } from '../src/utils/plural.js'

const RU = '{n} подписчик|{n} подписчика|{n} подписчиков'

test('русский: три формы и «21 — снова один»', () => {
  const got = (n) => pickPlural(RU, n, 'ru').replace('{n}', n)
  assert.equal(got(1), '1 подписчик')
  assert.equal(got(2), '2 подписчика')
  assert.equal(got(5), '5 подписчиков')
  assert.equal(got(11), '11 подписчиков')
  assert.equal(got(21), '21 подписчик')
  assert.equal(got(502), '502 подписчика')
  assert.equal(got(501), '501 подписчик')
  assert.equal(got(0), '0 подписчиков')
})

test('английский: две формы; строка без «|» — как есть', () => {
  assert.equal(pickPlural('{n} member|{n} members', 1, 'en'), '{n} member')
  assert.equal(pickPlural('{n} member|{n} members', 7, 'en'), '{n} members')
  assert.equal(pickPlural('{n} 位成员', 7, 'zh'), '{n} 位成员')
})

test('перевод подставляет форму по числу (проводка в сторе локали)', () => {
  const src = readFileSync(new URL('../src/stores/locale.js', import.meta.url), 'utf8')
  assert.match(src, /pickPlural\(s, params\.n,/, 'стор локали не выбирает форму по числу')
})

test('счётчики подписчиков и участников заданы формами', () => {
  const dict = readFileSync(new URL('../src/i18n/dictionaries.js', import.meta.url), 'utf8')
  for (const key of ['messenger.subscribersCount', 'conversationInfo.subscribersCount',
                     'conversationInfo.membersCount']) {
    const ru = dict.match(new RegExp(`'${key.replace('.', '\\.')}': '([^']*)'`))
    assert.ok(ru && ru[1].split('|').length === 3, `${key}: у русской строки не три формы`)
  }
})
