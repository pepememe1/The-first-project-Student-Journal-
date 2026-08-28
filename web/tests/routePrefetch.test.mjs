/**
 * routePrefetch.test.mjs — страницы разрезаны по маршрутам и греются в фоне.
 *
 * Зачем сторож. До 28.08.2026 роутер импортировал все 45 страниц СТАТИЧЕСКИ, и сборщик
 * складывал их в один файл на 1 468 кБ: студент качал вместе со своим кабинетом админку,
 * модерацию и раздел сервера. После нарезки — 347 кБ.
 *
 * 🔥 Откат сюда вносится ОДНОЙ строкой и молча: достаточно дописать `import X from
 * '@/pages/...'` вместо `const X = () => import(...)`, и страница снова уедет в общий
 * бандл. Ни сборка, ни линтер этого не заметят — размер просто вырастет. Поэтому форму
 * импортов проверяем текстом файла.
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { lazyLoadersForRole, prefetchRoutes } from '../src/utils/routePrefetch.js'

const ROUTER = readFileSync(fileURLToPath(new URL('../src/router/index.js', import.meta.url)), 'utf8')

//Статическими остаются ровно три: оболочка и два экрана первого кадра.
const ALLOWED_STATIC = ['AppShell', 'LoginPage', 'NotFoundPage']

test('страницы импортируются ЛЕНИВО, а не статически', () => {
  const statics = [...ROUTER.matchAll(/^import (\w+) from '(@\/(?:pages|layouts)\/[^']+)'$/gm)]
    .map((m) => m[1])
  const unexpected = statics.filter((n) => !ALLOWED_STATIC.includes(n))
  assert.deepEqual(unexpected, [],
    `эти страницы вернулись в общий бандл: ${unexpected.join(', ')}`)

  //Обратный ход: ленивых загрузчиков должно быть МНОГО. Если правку откатят целиком,
  //список статических окажется пустым по другой причине — потому что импортов не стало.
  const lazy = [...ROUTER.matchAll(/const \w+ = \(\) => import\('@\/pages\//g)].length
  assert.ok(lazy > 30, `ленивых страниц всего ${lazy} — нарезка не состоялась`)
})

test('первый кадр не откладывается: оболочка и вход грузятся сразу', () => {
  //Отложить их значило бы добавить сетевой круг ровно там, где задержка заметнее всего.
  for (const name of ['AppShell', 'LoginPage']) {
    assert.ok(new RegExp(`^import ${name} from '@/`, 'm').test(ROUTER),
      `${name} стал ленивым — это видимая пауза перед первым экраном`)
  }
})

// ── Отбор загрузчиков по роли ────────────────────────────────────────────────────────
const fakeRoutes = [
  { path: '/student', meta: { role: 'student' }, component: {}, children: [
    { path: 'journal', component: () => Promise.resolve({}) },
    { path: 'stats', component: () => Promise.resolve({}) },
  ] },
  { path: '/admin', meta: { role: 'admin' }, component: {}, children: [
    { path: 'server', component: () => Promise.resolve({}) },
  ] },
  //Ветка без роли (вход, 404) со СТАТИЧЕСКИМ компонентом — её звать нельзя.
  { path: '/login', component: {}, children: [] },
]

test('греем только СВОЮ роль', () => {
  //Тянуть студенту админку значило бы вернуть тот же единый мегабайт другим путём.
  assert.equal(lazyLoadersForRole(fakeRoutes, 'student').length, 2)
  assert.equal(lazyLoadersForRole(fakeRoutes, 'admin').length, 1)
})

test('статический компонент не попадает в прогрев', () => {
  //У статических маршрутов `component` — объект, а не функция; вызов его сломал бы всё.
  const loaders = lazyLoadersForRole(fakeRoutes, 'student')
  for (const l of loaders) assert.equal(typeof l, 'function')
})

test('без роли не греем ничего', async () => {
  assert.equal(await prefetchRoutes(fakeRoutes, ''), 0)
})

test('сбой загрузки одной страницы не роняет прогрев', async () => {
  const routes = [{ path: '/x', meta: { role: 'student' }, component: {}, children: [
    { path: 'a', component: () => Promise.reject(new Error('сеть моргнула')) },
    { path: 'b', component: () => Promise.resolve({}) },
  ] }]
  //Прогрев — не событие: упавшая страница просто доедет при переходе, как и до правки.
  assert.equal(await prefetchRoutes(routes, 'student'), 1)
})
