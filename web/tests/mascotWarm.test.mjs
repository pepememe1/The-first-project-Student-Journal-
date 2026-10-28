// mascotWarm.test.mjs — анимации Вектора в очередь прогрева по одной (28.10.2026).
//
// Первое открытие Вектора не должно показывать пустое место, пока качается анимация, но и
// пачка в 2.3 МБ разом не должна отбирать канал у того, что человек открыл в эту секунду.
import { test } from 'node:test'
import assert from 'node:assert/strict'

const started = []
class FakeImage {
  set src(v) { started.push(v); queueMicrotask(() => this.onload?.()) }
}

test('загрузчики по одному, без повтора; экономия трафика — ничего', async () => {
  globalThis.Image = FakeImage
  const { animLoaders, CHAT_ANIMS } = await import('../src/config/mascot.js')

  //Экономия трафика: заранее не тянем ничего (lowBandwidth).
  Object.defineProperty(globalThis, 'navigator', { value: { connection: { saveData: true } }, configurable: true })
  assert.deepEqual(animLoaders('chat'), [])

  Object.defineProperty(globalThis, 'navigator', { value: { connection: { saveData: false } }, configurable: true })
  const loaders = animLoaders('chat')
  assert.equal(loaders.length, CHAT_ANIMS.length)
  assert.equal(started.length, 0, 'вызов animLoaders сам ничего не качает — качает очередь')
  await loaders[0]()
  assert.equal(started.length, 1, 'один загрузчик — один файл')
  assert.deepEqual(animLoaders('chat'), [], 'второй прогрев той же области не нужен')
})
