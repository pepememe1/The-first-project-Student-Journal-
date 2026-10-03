// dialogA11y.test.mjs — доступность первого ряда (docs/operations/ACCESSIBILITY.md;
// план «Золото», веха М2): окна объявлены диалогами и держат фокус, уведомления
// озвучиваются, есть переход «к содержимому».
//
// Браузера в прогоне нет, поэтому проверяем РЕШЕНИЕ (куда идёт фокус по Tab — чистая
// функция) и ПРОВОДКУ (каждое окно под директивой). Второе — свойство по всему каталогу
// компонентов: новое окно без директивы покраснеет само, а не будет найдено ревью.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { nextFocusIndex } from '../src/directives/dialog.js'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const read = (rel) => readFileSync(join(SRC, rel), 'utf8')

test('Tab ходит по кругу внутри окна', () => {
  assert.equal(nextFocusIndex(3, 0, false), 1)
  assert.equal(nextFocusIndex(3, 2, false), 0, 'с последнего — на первый, а не под окно')
  assert.equal(nextFocusIndex(3, 0, true), 2, 'Shift+Tab с первого — на последний')
  assert.equal(nextFocusIndex(3, 1, true), 0)
})

test('фокус снаружи окна возвращается внутрь', () => {
  assert.equal(nextFocusIndex(4, -1, false), 0)
  assert.equal(nextFocusIndex(4, -1, true), 3)
  assert.equal(nextFocusIndex(0, -1, false), -1, 'пустое окно — некуда')
})

function* dialogFiles(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* dialogFiles(p)
    else if (/(Dialog|Modal)\.vue$/.test(name)) yield p
  }
}

function withoutDirective(files) {
  return files.filter((p) => !/<div[^>]*\bv-dialog\b/.test(readFileSync(p, 'utf8')))
}

test('каждое окно (*Dialog.vue, *Modal.vue) — под v-dialog', () => {
  const files = [...dialogFiles(join(SRC, 'components'))]
  assert.ok(files.length >= 20, `окон нашлось подозрительно мало: ${files.length}`)
  assert.deepEqual(withoutDirective(files), [])
})

test('обратный ход: окно без директивы находится', () => {
  const p = join(SRC, 'components/ui/ConfirmDialog.vue')
  const broken = readFileSync(p, 'utf8').replace('<div v-dialog', '<div')
  assert.equal(/<div[^>]*\bv-dialog\b/.test(broken), false)
})

test('директива зарегистрирована глобально', () => {
  assert.match(read('main.js'), /app\.directive\('dialog', vDialog\)/)
})

test('уведомления — живая область, существующая заранее, ошибки — alert', () => {
  const host = read('components/ui/ToastHost.vue')
  const container = host.slice(host.indexOf('<template>'), host.indexOf('v-for="t in toasts"'))
  assert.match(container, /aria-live="polite"/, 'область обязана быть на контейнере, а не на тосте')
  assert.match(host, /t\.type === 'error' \? 'alert' : 'status'/)
})

test('ссылка «к содержимому» ведёт на main, и main принимает фокус', () => {
  const shell = read('layouts/AppShell.vue')
  assert.match(shell, /<a href="#gb-main"/)
  assert.match(shell, /<main id="gb-main" tabindex="-1"/)
})

// ── Кнопка без текста обязана иметь подпись ─────────────────────────────────────────
// Кнопка-значок (крестик, корзина, стрелка) без `aria-label` озвучивается просто
// «кнопка». Подпись дают `aria-label`/`title`; картинка с `alt` и `<slot />` подписывают
// себя сами.
function* vueFiles(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* vueFiles(p)
    else if (name.endsWith('.vue')) yield p
  }
}

function unlabeledIconButtons(text) {
  const tpl = text.slice(Math.max(0, text.indexOf('<template')))
  const bad = []
  for (const m of tpl.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)) {
    const [, attrs, inner] = m
    if (/aria-label|title=|v-bind/.test(attrs)) continue
    if (/<img\b|<slot\b/.test(inner)) continue
    const text = inner.replace(/\{\{[\s\S]*?\}\}/g, 'X').replace(/<[^>]+>/g, '').trim()
    if (text && !/^[\s✕×✓←→↑↓…⋯▸▾◂▴•·+−-]+$/.test(text)) continue
    bad.push(inner.trim().slice(0, 30))
  }
  return bad
}

test('у каждой кнопки-значка есть подпись', () => {
  const found = []
  for (const p of vueFiles(SRC)) {
    const bad = unlabeledIconButtons(readFileSync(p, 'utf8'))
    if (bad.length) found.push(`${p}: ${bad.join(' | ')}`)
  }
  assert.deepEqual(found, [])
})

test('обратный ход: крестик без подписи находится', () => {
  const src = '<template><button @click="close"><X class="size-5" /></button></template>'
  assert.equal(unlabeledIconButtons(src).length, 1)
  const ok = '<template><button :aria-label="t(\'common.close\')" @click="close"><X /></button></template>'
  assert.equal(unlabeledIconButtons(ok).length, 0)
})

// ── Окно в окне: Tab двигает только ближайшее окно ──────────────────────────────────
// Жалоба открывается поверх профиля собеседника (PeerProfileModal → PeerProfileCard →
// ReportUserDialog), и keydown всплывает к внешнему окну. Без проверки оба окна двигали
// фокус: Tab перепрыгивал через поле, а с конца жалобы уходил на кнопки под ней.
import { ownsEvent } from '../src/directives/dialog.js'

function fakeNode(modalAncestor) {
  return { closest: (sel) => (sel === '[aria-modal="true"]' ? modalAncestor : null) }
}

test('Tab из вложенного окна не обрабатывает внешнее', () => {
  const outer = { name: 'профиль' }
  const inner = { name: 'жалоба' }
  assert.equal(ownsEvent(outer, fakeNode(inner)), false, 'внешнее окно обязано промолчать')
  assert.equal(ownsEvent(inner, fakeNode(inner)), true)
  assert.equal(ownsEvent(outer, fakeNode(outer)), true)
  assert.equal(ownsEvent(outer, fakeNode(null)), true, 'фокус ещё снаружи — окно забирает его')
})

test('обработчик Tab спрашивает ownsEvent до того, как двигать фокус', () => {
  const src = readFileSync(join(SRC, 'directives/dialog.js'), 'utf8')
  const body = src.slice(src.indexOf('onKey = (e) =>'), src.indexOf("addEventListener('keydown'"))
  assert.ok(body.indexOf('ownsEvent(el, e.target)') > 0, 'проверки вложенного окна нет')
  assert.ok(body.indexOf('ownsEvent(el, e.target)') < body.indexOf('.focus()'))
})
