// vectorQueue.test.mjs — набранное у Вектора не пропадает (28.10.2026, находка N9).
//
// Было: Enter, пока Вектор думал, молча ничего не делал, а быстрая команда или голос
// стирали то, что человек набирал в поле. Стор тянет за собой API, озвучку и вход, поэтому
// проверка — по тексту стора, как у соседних сторожей.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readSource } from './_readSource.mjs'

const store = readSource('stores/vector.js')
const send = store.slice(store.indexOf('async function send('), store.indexOf('function ask('))

test('поле чистится только когда вопрос из него', () => {
  const clears = [...send.matchAll(/input\.value = ''/g)]
  assert.ok(clears.length >= 1, 'отправка больше не чистит поле — проверка ослепла')
  for (const m of clears) {
    const line = send.slice(send.lastIndexOf('\n', m.index), m.index)
    assert.match(line, /if \(fromInput\)/, 'поле чистится и для быстрой команды или голоса')
  }
})

test('вопрос во время ответа встаёт в очередь и уходит следом', () => {
  const thinking = send.slice(send.indexOf("state.value === 'thinking'"))
  assert.match(thinking.slice(0, 200), /queued\.value = \{/, 'Enter во время ответа снова глотается')
  const tail = send.slice(send.lastIndexOf('} finally {'))
  assert.match(tail, /if \(next\) send\(next\.text, next\.displayText\)/, 'очередь не отправляется')
  assert.match(store.slice(store.indexOf('function reset()')), /queued\.value = null/,
    'очередь переживает выход из аккаунта — чужой вопрос ушёл бы от нового человека')
})

test('кнопка отправки не выключается на время ответа', () => {
  for (const file of ['pages/VectorPage.vue', 'components/VectorDock.vue']) {
    const src = readSource(file)
    assert.ok(!/:disabled="state === 'thinking'/.test(src), `${file}: кнопка снова глохнет, пока Вектор думает`)
    assert.match(src, /vectorPage\.queued/, `${file}: не показано, какой вопрос ждёт очереди`)
  }
})
