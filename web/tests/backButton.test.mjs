// backButton.test.mjs — системная кнопка «назад» на телефоне (23.10.2026).
//
// Проверено на Android 16: без своего обработчика плагин @capacitor/app только листал
// историю WebView. На главном экране кнопка не делала ничего, открытые подсказка и меню
// доступности не закрывались. Теперь «назад» закрывает верхнее окно или панель, потом
// возвращает на прошлый экран, а с главного сворачивает приложение.
//
// Браузера в прогоне нет: очередь слоёв и директивы гоняются на поддельных элементах,
// решение — чистой функцией. Последний тест — свойство по всему web/src: у подложки без
// директивы «назад» уводил бы страницу из-под открытого окна.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

globalThis.window = { addEventListener: () => {}, removeEventListener: () => {} }
globalThis.document = { activeElement: null, contains: () => false }
globalThis.requestAnimationFrame = () => {}

const { decideBack } = await import('../src/utils/backButton.js')
const { vBackClose, topLayer, closeTopLayer, pushLayer, removeLayer } =
  await import('../src/utils/backLayers.js')
const { vDialog } = await import('../src/directives/dialog.js')

const ROOTS = ['/', '/login', '/student', '/teacher', '/admin', '/parent', '/moderator']

function fakeEl(name, { rects = 1 } = {}) {
  const attrs = {}
  return {
    name, clicks: 0, isConnected: true,
    getClientRects: () => Array.from({ length: rects }),
    setAttribute: (k, v) => { attrs[k] = v },
    hasAttribute: (k) => k in attrs,
    querySelector: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
    contains: () => false,
    click() { this.clicks += 1 },
  }
}

test('открыто окно — сначала закрыть его, даже на главном экране', () => {
  assert.equal(decideBack({ hasLayer: true, path: '/teacher', roots: ROOTS, canGoBack: true }), 'layer')
  assert.equal(decideBack({ hasLayer: true, path: '/teacher/journal', roots: ROOTS, canGoBack: false }), 'layer')
})

test('главный экран и вход сворачивают приложение, даже если в истории что-то есть', () => {
  //После входа в истории лежит /login: шаг назад с главного вёл бы на вход, а оттуда
  //маршрутизатор возвращает обратно — кнопка снова «ничего не делала» бы.
  for (const path of ['/student', '/teacher', '/login', '/']) {
    assert.equal(decideBack({ hasLayer: false, path, roots: ROOTS, canGoBack: true }), 'minimize', path)
  }
})

test('внутренний экран: есть история — шаг назад, нет — на главный', () => {
  assert.equal(decideBack({ hasLayer: false, path: '/teacher/journal', roots: ROOTS, canGoBack: true }), 'history')
  assert.equal(decideBack({ hasLayer: false, path: '/student/messages', roots: ROOTS, canGoBack: false }), 'home')
})

test('закрывается только верхний слой, после него — следующий', () => {
  const lower = fakeEl('профиль')
  const upper = fakeEl('жалоба')
  vBackClose.mounted(lower, { value: undefined })
  vBackClose.mounted(upper, { value: undefined })
  assert.equal(closeTopLayer(), true)
  assert.equal(upper.clicks, 1, 'верхняя панель не получила щелчок по подложке')
  assert.equal(lower.clicks, 0, 'закрылась и панель под ней')
  vBackClose.unmounted(upper)
  closeTopLayer()
  assert.equal(lower.clicks, 1)
  vBackClose.unmounted(lower)
  assert.equal(closeTopLayer(), false, 'после закрытия всех слоёв закрывать нечего')
})

test('скрытый и снятый со страницы слой «назад» не ловит', () => {
  //Боковая панель на широком экране скрыта (`lg:hidden`), а стрелка «к списку чатов»
  //видна только на телефоне: невидимое не должно съедать нажатие.
  const hidden = fakeEl('скрытая', { rects: 0 })
  const gone = fakeEl('снятая')
  gone.isConnected = false
  pushLayer(hidden, () => hidden.click())
  pushLayer(gone, () => gone.click())
  assert.equal(topLayer(), null)
  assert.equal(closeTopLayer(), false)
  removeLayer(hidden)
  removeLayer(gone)
})

test('стрелка «Назад» внутри окна главнее окна, даже если встала в очередь раньше', () => {
  //Vue монтирует дочерние элементы раньше родителя: стрелка встаёт в очередь первой.
  const overlay = fakeEl('меню активностей')
  const backArrow = fakeEl('стрелка к списку категорий')
  overlay.contains = (el) => el === backArrow
  vBackClose.mounted(backArrow, { value: undefined })
  vBackClose.mounted(overlay, { value: undefined })
  closeTopLayer()
  assert.equal(backArrow.clicks, 1, 'окно закрылось целиком, минуя шаг назад внутри')
  assert.equal(overlay.clicks, 0)
  vBackClose.unmounted(backArrow)
  closeTopLayer()
  assert.equal(overlay.clicks, 1)
  vBackClose.unmounted(overlay)
})

test('со значением-функцией директива зовёт свежую функцию, а не щёлкает', () => {
  const el = fakeEl('меню')
  let calls = ''
  vBackClose.mounted(el, { value: () => { calls += 'старая' } })
  vBackClose.updated(el, { value: () => { calls += 'новая' } })
  closeTopLayer()
  assert.equal(calls, 'новая', 'вызвана функция с прошлой отрисовки')
  assert.equal(el.clicks, 0)
  vBackClose.unmounted(el)
})

test('окно v-dialog встаёт в очередь «назад» само и закрывается щелчком по подложке', () => {
  const panel = fakeEl('панель')
  const dialog = fakeEl('окно')
  vBackClose.mounted(panel, { value: undefined })
  vDialog.mounted(dialog)
  closeTopLayer()
  assert.equal(dialog.clicks, 1, 'окно, открытое поверх панели, не закрылось первым')
  assert.equal(panel.clicks, 0)
  vDialog.unmounted(dialog)
  assert.equal(topLayer()?.el, panel, 'закрытое окно осталось в очереди')
  vBackClose.unmounted(panel)
})

test('приложение подключает обработчик кнопки на старте', () => {
  //Обработчик без вызова — то же, что его отсутствие: кнопка снова листала бы историю.
  const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8')
  assert.match(main, /installBackButton\(router,/)
  assert.match(main, /app\.directive\('back-close', vBackClose\)/)
})

function vueFiles(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...vueFiles(p))
    else if (name.endsWith('.vue')) out.push(p)
  }
  return out
}

test('каждая подложка на весь экран закрывается кнопкой «назад»', () => {
  //Подложка `fixed inset-0` — это окно или меню поверх страницы. Без v-dialog или
  //v-back-close «назад» уводит страницу из-под него, а оно остаётся висеть.
  //Исключение — слои с pointer-events-none: они не перехватывают касания и закрываются сами.
  //Метка разбирается по атрибутам: значение в кавычках может содержать «>»
  //(`v-back-close="() => emit('close')"`), и простое `[^>]*` такую метку не видело вовсе.
  const src = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
  const tag = /<[a-zA-Z][\w-]*(?:\s+[^\s"'=<>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'))?)*\s*\/?>/g
  const missing = []
  let overlays = 0
  for (const file of vueFiles(src)) {
    const text = readFileSync(file, 'utf8')
    const from = Math.max(0, text.indexOf('<template'))
    for (const m of text.slice(from).matchAll(tag)) {
      const t = m[0]
      //С префиксом ширины тоже (`lg:fixed lg:inset-0` — окно Настроек на планшете) и в
      //любом порядке классов: буквальное «fixed inset-0» их не видело (Полковник 23.10.2026).
      const cls = /(?<![\w-])(?:[a-z0-9]+:)*/.source
      if (!new RegExp(`${cls}fixed(?![\\w-])`).test(t)) continue
      if (!new RegExp(`${cls}inset-0(?![\\w-])`).test(t)) continue
      overlays += 1
      if (/\bv-dialog\b|\bv-back-close\b|pointer-events-none/.test(t)) continue
      missing.push(`${file.slice(src.length)}: ${t.replace(/\s+/g, ' ').slice(0, 120)}`)
    }
  }
  //Слепой разбор нашёл бы ноль подложек и молча прошёл бы: их в интерфейсе десятки.
  assert.ok(overlays >= 70, `разбор нашёл только ${overlays} подложек`)
  assert.deepEqual(missing, [], 'подложки без v-dialog или v-back-close')
})
