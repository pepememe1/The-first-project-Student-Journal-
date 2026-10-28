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

// ── Ленивые части оболочки (utils/lazyComponent.js, 28.10.2026) ──────────────────────
//Переводы строк — к \n: на диске с CRLF `$` в многострочной регулярке не срабатывает,
//и сторож статических импортов был бы слеп на Windows.
const SRC = (p) => readFileSync(fileURLToPath(new URL('../src/' + p, import.meta.url)), 'utf8').replace(/\r\n/g, '\n')

test('ленивые части оболочки греются первыми, страницы роли — следом', async () => {
  const order = []
  const routes = [{ path: '/s', meta: { role: 'student' }, component: {}, children: [
    { path: 'a', component: () => { order.push('page'); return Promise.resolve({}) } },
  ] }]
  const extra = [() => { order.push('dock'); return Promise.resolve({}) }]
  assert.equal(await prefetchRoutes(routes, 'student', extra), 2)
  //Шторку Вектора и окна активностей открывают со страницы, на которой человек уже стоит:
  //они должны быть на месте раньше, чем страницы, до которых ещё надо дойти по меню.
  assert.deepEqual(order, ['dock', 'page'])
})

test('на экономном режиме части оболочки греются, страницы — нет', async () => {
  //Части оболочки раньше лежали в главном чанке и грузились всегда — прогрев не тратит
  //трафика сверх прежнего. Страницы впрок на экономном режиме не качаем, как и до правки.
  const was = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'navigator', { value: { connection: { saveData: true } }, configurable: true })
  try {
    const order = []
    const routes = [{ path: '/s', meta: { role: 'student' }, component: {}, children: [
      { path: 'a', component: () => { order.push('page'); return Promise.resolve({}) } },
    ] }]
    await prefetchRoutes(routes, 'student', [() => { order.push('dock'); return Promise.resolve({}) }])
    assert.deepEqual(order, ['dock'])
  } finally {
    if (was) Object.defineProperty(globalThis, 'navigator', was)
    else delete globalThis.navigator
  }
})

test('оболочка отдаёт свои ленивые части в прогрев', () => {
  //Без этого вызова service worker не положит чанк в кэш, и без сети шторка Вектора не
  //открылась бы у того, кто ни разу её не открывал.
  assert.match(SRC('layouts/AppShell.vue'), /prefetchRoutes\(appRoutes, auth\.role, \[\.\.\.warmLoaders\(\), warmEmojiFont\]\)/)
})

test('прогревы вызваны там, где обещаны', () => {
  //Функция прогрева без вызывающего молча не греет ничего — тесты её поведения остались бы
  //зелёными, а первое открытие Вектора или окна второго фактора снова показывало бы подгрузку.
  const shell = SRC('layouts/AppShell.vue')
  assert.match(shell, /\.then\(\(\) => prefetchLoaders\(animLoaders\('chat'\)\)\)/, 'анимации Вектора')
  assert.match(shell, /warmAlso\(\(\) => import\('@\/components\/activity\/quiz\/QuizEditor\.vue'\)\)/, 'редактор квиза')
  assert.match(SRC('pages/LoginPage.vue'), /prefetchLoaders\(\[\.\.\.Object\.values\(LOGIN_DIALOGS\), warmEmojiFont\]\)/, 'окна входа и шрифт')
  assert.match(SRC('components/activity/ActivityLauncher.vue'), /prefetchLoaders\(\[loadQuizEditor\]\)/, 'редактор при открытом колесе')
})

test('то, что открывает меньшинство, не вернулось в главный чанк', () => {
  //По файлу, а не по имени переменной: импорт под другим именем тянет тот же чанк.
  const statics = (file) => [...SRC(file).matchAll(/^import \w+ from '[^']*\/(\w+)\.vue'$/gm)].map((m) => m[1])
  const heavy = {
    'layouts/AppShell.vue': ['VectorDock', 'ActivityLauncher', 'ActivityPortfolio', 'AccountOnboardingDialog'],
    'components/activity/ActivityShell.vue': ['QuizPlayer', 'BoardCanvas', 'PulsePlayer', 'PollPlayer', 'TimerPanel', 'ActivityPortfolio'],
    'pages/LoginPage.vue': ['MfaPrompt', 'DeviceApproval', 'RegisterDialog', 'RecoverDialog', 'PasswordRecoveryDialog'],
  }
  for (const [file, names] of Object.entries(heavy)) {
    const back = statics(file).filter((n) => names.includes(n))
    assert.deepEqual(back, [], `${file}: статический импорт снова тянет их в первую загрузку`)
  }
})
