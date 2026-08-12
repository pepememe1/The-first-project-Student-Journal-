// freshness.test.mjs — подпись «когда данные приходили с сервера».
//
// Функция чистая и принимает «сейчас» параметром — именно поэтому её и можно проверить:
// иначе тест зависел бы от часов машины и краснел бы раз в сутки около полуночи.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { freshness } from '../src/utils/freshness.js'

const NOW = new Date('2026-08-12T15:00:00').getTime()
const MIN = 60_000

test('данных не было ни разу — так и говорим, а не «только что»', () => {
  assert.deepEqual(freshness(0, NOW), { kind: 'never' })
})

test('свежее минуты — «только что»', () => {
  assert.equal(freshness(NOW - 30_000, NOW).kind, 'now')
})

test('до часа считаем минутами', () => {
  assert.deepEqual(freshness(NOW - 40 * MIN, NOW), { kind: 'minutes', n: 40 })
})

test('в тот же день — время', () => {
  const f = freshness(new Date('2026-08-12T09:05:00').getTime(), NOW)
  assert.equal(f.kind, 'today')
  assert.equal(f.time, '09:05')
})

test('вчера — отдельная формулировка', () => {
  const f = freshness(new Date('2026-08-11T22:30:00').getTime(), NOW)
  assert.equal(f.kind, 'yesterday')
  assert.equal(f.time, '22:30')
})

test('раньше — дата с временем', () => {
  const f = freshness(new Date('2026-08-09T07:04:00').getTime(), NOW)
  assert.equal(f.kind, 'date')
  assert.equal(f.date, '09.08')
  assert.equal(f.time, '07:04')
})

test('метка из будущего не превращается в «через два часа»', () => {
  // Часы устройства перевели назад — разница отрицательная. Считать её как «свежее
  // некуда» опасно: ровно этим приёмом и продлевают доступ к чужому телефону.
  const f = freshness(NOW + 2 * 3600_000, NOW)
  assert.equal(f.kind, 'date', 'показываем дату как есть, а не выдумываем давность')
})

test('около полуночи давность важнее календаря', () => {
  // 00:10, данные от 23:50. Календарно это «вчера», но человеку нужнее знать, что
  // прошло двадцать минут: «вчера в 23:50» звучит куда более устаревшим, чем есть.
  // Порядок проверок в функции задан именно поэтому, и тест закрепляет его намеренно.
  const now = new Date('2026-08-12T00:10:00').getTime()
  const f = freshness(new Date('2026-08-11T23:50:00').getTime(), now)
  assert.deepEqual(f, { kind: 'minutes', n: 20 })
})

test('а вот полтора часа через полночь — уже «вчера»', () => {
  const now = new Date('2026-08-12T00:40:00').getTime()
  const f = freshness(new Date('2026-08-11T23:00:00').getTime(), now)
  assert.equal(f.kind, 'yesterday')
  assert.equal(f.time, '23:00')
})
