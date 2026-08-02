// gifEmbed.test.mjs — распознавание голых ссылок на CDN Klipy в тексте сообщения
// (3.5.5). Чистая функция, без сети — тот же приём, что у videoEmbed.js.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { detectGifLink, extractGifLinks } from '../src/utils/gifEmbed.js'

test('ссылка на static.klipy.com распознаётся', () => {
  const g = detectGifLink('https://static.klipy.com/gifs/abc123.gif')
  assert.deepEqual(g, { sourceUrl: 'https://static.klipy.com/gifs/abc123.gif' })
})

test('чужой хост — null (белый список ровно один — как и на сервере gif_service.py)', () => {
  assert.equal(detectGifLink('https://klipy.com/gifs/abc123'), null)
  assert.equal(detectGifLink('https://evil.com/static.klipy.com.gif'), null)
  assert.equal(detectGifLink('https://example.com/'), null)
})

test('нет протокола http(s) — null (не открываем произвольные схемы)', () => {
  assert.equal(detectGifLink('javascript:alert(1)'), null)
  assert.equal(detectGifLink('static.klipy.com/gifs/abc123.gif'), null)
})

test('extractGifLinks достаёт ссылку из сырого текста, режет висящую пунктуацию', () => {
  const gifs = extractGifLinks('смотри https://static.klipy.com/g/x.gif. и вот https://example.com/y')
  assert.equal(gifs.length, 1)
  assert.equal(gifs[0].sourceUrl, 'https://static.klipy.com/g/x.gif')
})

test('extractGifLinks не дублирует одну и ту же ссылку дважды', () => {
  const gifs = extractGifLinks('https://static.klipy.com/g/x.gif и снова https://static.klipy.com/g/x.gif')
  assert.equal(gifs.length, 1)
})

test('пустой/отсутствующий текст — пустой список', () => {
  assert.deepEqual(extractGifLinks(''), [])
  assert.deepEqual(extractGifLinks(undefined), [])
})
