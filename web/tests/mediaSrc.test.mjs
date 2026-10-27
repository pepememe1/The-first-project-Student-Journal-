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
import { readSource } from './_readSource.mjs'

//api/server.js читает адрес сервера из localStorage при загрузке модуля.
globalThis.localStorage ??= { getItem: () => null, setItem() {}, removeItem() {} }
const { gifPosterSrc, gifStillSrc, gifVideoSrc, klipyMirror, mediaSrc } =
  await import('../src/utils/mediaSrc.js')
const { getApiBase } = await import('../src/api/server.js')

test('телефон — не программа: гифка идёт с нашего сервера, а не в несуществующий кэш программы', () => {
  //Приложение Android открыто с https://localhost — тоже петля. До 23.10.2026 гифки там
  //уходили на /desk/media, которого в телефоне нет, и не показывались вовсе.
  //Обратный ход: убрать проверку Capacitor из isPcProgram — краснеет.
  const saved = globalThis.window
  try {
    globalThis.window = { location: { hostname: 'localhost', port: '' },
      Capacitor: { isNativePlatform: () => true } }
    //Страница приложения открыта с https://localhost: адрес — от сервера, как у аватарки.
    const base = getApiBase()
    assert.ok(base.startsWith('https://'), 'в приложении адрес сервера обязан быть известен')
    assert.equal(mediaSrc(GIF), base + MIRROR)
    assert.equal(gifVideoSrc(GIF), base + MIRROR.replace(/\.gif$/, '.mp4'))
    globalThis.window = { location: { hostname: '127.0.0.1', port: '51234' } }
    assert.equal(mediaSrc(GIF), '/desk/media?u=' + encodeURIComponent(GIF), 'программа: через свой кэш')
    assert.equal(gifVideoSrc(GIF), '', 'кэш программы принимает только картинки')
    //Первый кадр — картинка, его кэш программы принимает: запасной вид есть и там.
    assert.equal(gifStillSrc(GIF), '/desk/media?u=' + encodeURIComponent(GIF.replace(/\.gif$/, '.webp')))
  } finally {
    globalThis.window = saved
  }
})

const GIF = 'https://static.klipy.com/ii/8ce8357c78ea940b9c2015daf05ce1a5/77/54/Bdsl9Upy.gif'
//Та же гифка с нашего сервера (27.10.2026): без VPN CDN Klipy открывается не у всех.
const MIRROR = '/media/klipy/ii/8ce8357c78ea940b9c2015daf05ce1a5/77/54/Bdsl9Upy.gif'

test('сайт: гифка, ролик и первый кадр — с нашего сервера, по тому же пути', () => {
  //Обратный ход: вернуть в mediaSrc «как есть» для Klipy — краснеет первая строка.
  assert.equal(mediaSrc(GIF), MIRROR)
  assert.equal(gifVideoSrc(GIF), MIRROR.replace(/\.gif$/, '.mp4'))
  assert.equal(gifPosterSrc(GIF), MIRROR.replace(/\.gif$/, '.webp'))
  assert.equal(gifStillSrc(GIF), MIRROR.replace(/\.gif$/, '.webp'))
  assert.equal(gifVideoSrc(GIF.replace('.gif', '.GIF')), MIRROR.replace(/\.gif$/, '.mp4'))
})

test('мимо шаблона сервера — без подмены: такой путь он не возьмёт', () => {
  assert.equal(klipyMirror(GIF + '?x=1'), '', 'запрос в адресе сервер отбрасывает')
  //`..` разбор адреса сворачивает сам; символы мимо шаблона — отказ.
  assert.equal(klipyMirror('https://static.klipy.com/ii/x%20y.gif'), '')
  assert.equal(klipyMirror('https://static.klipy.com/ii/x.svg'), '', 'только картинки и ролики')
  assert.equal(klipyMirror('https://evil.example/ii/x.gif'), '')
  assert.equal(gifStillSrc(GIF.replace(/\.gif$/, '.webp')), '', 'кадр есть только у гифки')
  assert.equal(gifStillSrc('data:image/png;base64,AAAA'), '')
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

test('аватарка и баннер: первый кадр лежит ПОДЛОЖКОЙ — Klipy недоступен, кадр остаётся', () => {
  //Требование Влада 27.10.2026: «если клипи не работает — один кадр из гифки, как обычная
  //аватарка». Подложка, а не запасной путь после отказа: ждать таймаута CDN ради кадра
  //незачем. Обратный ход: убрать `stillOk` у значка роли — краснеет.
  const avatar = readSource('components/ui/Avatar.vue')
  assert.match(avatar, /const still = computed\(\(\) => gifStillSrc\(props\.src\)\)/)
  assert.match(avatar, /<img v-if="stillOk" :src="still"[^>]*absolute inset-0/)
  assert.match(avatar, /<RoleAvatarIcon v-else-if="hasRoleIcon && !stillOk"/,
    'значок роли не должен закрывать кадр гифки')
  const card = readSource('components/messenger/PeerProfileCard.vue')
  assert.match(card, /const bannerStill = computed\(\(\) => gifStillSrc\(bannerUrl\.value\)\)/)
  assert.match(card, /<img v-if="bannerStill && !bannerStillFailed" :src="bannerStill"/)
})
