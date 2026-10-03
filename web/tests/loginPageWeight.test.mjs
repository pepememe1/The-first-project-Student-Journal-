// loginPageWeight.test.mjs — страница входа не тянет то, чего человек не видит.
//
// 🔥 Дефект (01.10.2026, жалоба «с мобильного интернета сайт долго грузится и падает
// „ошибкой соединения“, а приложение входит мгновенно»). Колонка маскота на входе скрыта
// классом `hidden lg:block`, но компонент внутри монтировался всегда, и невидимый на
// телефоне Вектор качал приветствие, покой и оба жеста с глазами — около 1.65 МБ. В
// журнале боевого Caddy: POST /auth/login отвечал за 0.4 с, а до телефона ответ не
// доезжал — он стоял в одном соединении HTTP/2 за мегабайтами анимаций. Ни сборка, ни
// линтер этого не видят: на широком экране всё выглядит правильно.
//
// Второе: сервис-воркер клал в кэш ЛЮБОЙ `ok`-ответ, а анимации браузер докачивает
// частями (206). Cache API частичный ответ не берёт — копия не появлялась никогда, и
// каждый заход качал анимации заново.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const LOGIN = readFileSync(new URL('../src/pages/LoginPage.vue', import.meta.url), 'utf8')
const SW = readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8')
const MASCOT = readFileSync(new URL('../src/config/mascot.js', import.meta.url), 'utf8')
const AUTH = readFileSync(new URL('../src/stores/auth.js', import.meta.url), 'utf8')

/** Маскот на входе монтируется по признаку широкого экрана, а не только скрывается CSS. */
function mascotMountedOnlyWhenVisible(src) {
  const tag = src.match(/<Mascot\b[^>]*>/)
  if (!tag) return false
  if (!/\bv-if="wideScreen"/.test(tag[0])) return false
  //Граница обязана совпадать с классом `lg:` колонки: разойдись они — маскот пропал бы
  //на широком экране или снова качался бы невидимым на узком.
  const query = src.match(/WIDE_QUERY\s*=\s*'([^']+)'/)
  return !!query && query[1] === '(min-width: 1024px)' && /hidden[^"]*\blg:block/.test(src)
}

test('маскот на входе не монтируется там, где его не видно', () => {
  assert.equal(mascotMountedOnlyWhenVisible(LOGIN), true)
})

test('обратный ход: без v-if проверка краснеет', () => {
  const broken = LOGIN.replace(' v-if="wideScreen"', '')
  assert.notEqual(broken, LOGIN, 'обратный ход не нашёл строку, которую ломает')
  assert.equal(mascotMountedOnlyWhenVisible(broken), false)
})

test('сервис-воркер кладёт в кэш только полный ответ (200), а не 206', () => {
  assert.equal(/resp\.ok\s*&&/.test(SW), false, 'кэширование по resp.ok пропускает 206')
  const guards = SW.match(/resp\.status === 200/g) || []
  assert.equal(guards.length, 2, 'обе ветки кэширования обязаны требовать статус 200')
})

test('предзагрузка маскота уважает «экономию трафика»', async () => {
  const created = []
  globalThis.Image = class { set src(v) { created.push(v) } }
  const nav = globalThis.navigator
  Object.defineProperty(nav, 'connection', { value: { saveData: true }, configurable: true })
  const m = await import('../src/config/mascot.js')
  m.preloadAnims('login')
  m.preloadMascots()
  assert.deepEqual(created, [], 'при saveData заранее не грузится ничего')
  //Обратный ход: та же функция без экономии трафика грузит — значит молчание выше
  //заслуга проверки, а не поломанной функции.
  Object.defineProperty(nav, 'connection', { value: { saveData: false, effectiveType: '4g' }, configurable: true })
  m.preloadAnims('login')
  assert.equal(created.length, 3, 'покой и два жеста с глазами')
  delete nav.connection
  delete globalThis.Image
  assert.match(MASCOT, /export function lowBandwidth\(\)/)
})

test('вход без ответа сервера говорит, что делать, а не «проверьте соединение»', () => {
  const at = AUTH.indexOf('async function login(')
  const body = AUTH.slice(at, AUTH.indexOf('async function loginPasskey('))
  assert.match(body, /if \(isStaleSession\(e\)\) throw e/)
  assert.match(body, /const noAnswer = !e\.response/)
  assert.match(body, /else if \(noAnswer\) error\.value = 'Сервер не ответил\./)
  //Порядок значим: сначала отказ прежней сессии, потом «нет ответа».
  assert.ok(body.indexOf('isStaleSession(e)') < body.indexOf('!e.response'))
})
