// mediaSrc.test.mjs — гифки Klipy роликом и первым кадром (23.10.2026).
//
// GIF у аватарки весил 13,7 МБ, и телефон не показал его вовсе; тот же ролик в MP4 —
// 27 КБ, первый кадр webp — 55 КБ (проверено на CDN). Держится:
//   • гифка Klipy получает ролик `.mp4` и первый кадр `.webp` по тому же адресу;
//   • не-гифка и чужой хост — без подмены (там нечего облегчать или нельзя);
//   • аватарка и гифка в ленте сначала показывают первый кадр, ролик — когда видны.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: `klipyVariant`, отдающий исходный адрес, — краснеет первый
// тест; убрать `v-if="seen"` у ролика аватарки — краснеет последний.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

//api/server.js читает адрес сервера из localStorage при загрузке модуля.
globalThis.localStorage ??= { getItem: () => null, setItem() {}, removeItem() {} }
const { gifPosterSrc, gifVideoSrc, mediaSrc } = await import('../src/utils/mediaSrc.js')

test('телефон — не программа: гифка идёт с Klipy, а не в несуществующий кэш программы', () => {
  //Приложение Android открыто с https://localhost — тоже петля. До 23.10.2026 гифки там
  //уходили на /desk/media, которого в телефоне нет, и не показывались вовсе.
  //Обратный ход: убрать проверку Capacitor из isPcProgram — краснеет.
  const saved = globalThis.window
  try {
    globalThis.window = { location: { hostname: 'localhost', port: '' },
      Capacitor: { isNativePlatform: () => true } }
    assert.equal(mediaSrc(GIF), GIF)
    assert.equal(gifVideoSrc(GIF), GIF.replace(/\.gif$/, '.mp4'))
    globalThis.window = { location: { hostname: '127.0.0.1', port: '51234' } }
    assert.equal(mediaSrc(GIF), '/desk/media?u=' + encodeURIComponent(GIF), 'программа: через свой кэш')
    assert.equal(gifVideoSrc(GIF), '', 'кэш программы принимает только картинки')
  } finally {
    globalThis.window = saved
  }
})

const GIF = 'https://static.klipy.com/ii/8ce8357c78ea940b9c2015daf05ce1a5/77/54/Bdsl9Upy.gif'

test('гифка Klipy — ролик mp4 и первый кадр webp по тому же адресу', () => {
  assert.equal(gifVideoSrc(GIF), GIF.replace(/\.gif$/, '.mp4'))
  assert.equal(gifPosterSrc(GIF), GIF.replace(/\.gif$/, '.webp'))
  assert.equal(gifVideoSrc(GIF.replace('.gif', '.GIF')), GIF.replace(/\.gif$/, '.mp4'))
})

test('не гифка и чужой хост — без подмены', () => {
  assert.equal(gifVideoSrc(GIF.replace(/\.gif$/, '.webp')), '', 'превью и так лёгкое')
  assert.equal(gifVideoSrc('https://evil.example/x.gif'), '')
  assert.equal(gifVideoSrc('http://static.klipy.com/x.gif'), '', 'только https, как у isKlipyUrl')
  assert.equal(gifVideoSrc('data:image/png;base64,AAAA'), '')
  assert.equal(gifVideoSrc(''), '')
})

test('аватарка и гифка в ленте: первый кадр сразу, ролик — когда видны', () => {
  for (const file of ['../src/components/ui/Avatar.vue', '../src/components/messenger/GifImage.vue']) {
    const src = readFileSync(new URL(file, import.meta.url), 'utf8')
    assert.match(src, /gifVideoSrc\(props\.src\)/, `${file}: гифка снова целиком`)
    assert.match(src, /:poster="poster"/, `${file}: нет первого кадра`)
    assert.match(src, /watchInView\(box\.value/, `${file}: ролик качается и вне экрана`)
  }
  const avatar = readFileSync(new URL('../src/components/ui/Avatar.vue', import.meta.url), 'utf8')
  assert.match(avatar, /<video v-if="seen" ref="videoEl"/)
})
