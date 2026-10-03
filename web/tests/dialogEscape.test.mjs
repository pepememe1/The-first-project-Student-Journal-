// dialogEscape.test.mjs — Esc закрывает окно (02.10.2026).
//
// Живой прогон 01.10.2026: Esc не закрывал «Аттестацию», «Создать» в мессенджере, диалоги
// преподавателя. Esc теперь делает то же, что щелчок мимо окна: директива v-dialog щёлкает
// по подложке ВЕРХНЕГО окна, и срабатывает его собственный `@click.self` — решение о
// закрытии остаётся за компонентом.
//
// Браузера в прогоне нет — директива гоняется на поддельных элементах: проверяется
// ПОВЕДЕНИЕ (кого закрыли), а не текст файла.
import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const listeners = {}
globalThis.window = {
  addEventListener: (t, fn) => { (listeners[t] ||= new Set()).add(fn) },
  removeEventListener: (t, fn) => { listeners[t]?.delete(fn) },
}
globalThis.document = { activeElement: null, contains: () => false }
globalThis.requestAnimationFrame = () => {}

const { vDialog, topDialog, hasOpenDialog } = await import('../src/directives/dialog.js')

function fakeDialog(name) {
  const attrs = {}
  return {
    name, clicks: 0, isConnected: true,
    setAttribute: (k, v) => { attrs[k] = v },
    hasAttribute: (k) => k in attrs,
    querySelector: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
    contains: () => false,
    click() { this.clicks += 1 },
  }
}

function pressEsc(prevented = false) {
  const e = { key: 'Escape', defaultPrevented: prevented,
              preventDefault() { this.defaultPrevented = true } }
  for (const fn of [...(listeners.keydown || [])]) fn(e)
  return e
}

beforeEach(() => { for (const k of Object.keys(listeners)) listeners[k].clear() })

test('Esc щёлкает по подложке верхнего окна, нижнее не трогает', () => {
  const lower = fakeDialog('профиль')
  const upper = fakeDialog('жалоба')
  vDialog.mounted(lower)
  vDialog.mounted(upper)
  const e = pressEsc()
  assert.equal(upper.clicks, 1, 'верхнее окно не получило «щелчок мимо»')
  assert.equal(lower.clicks, 0, 'закрылось и окно под ним')
  assert.equal(e.defaultPrevented, true)
  vDialog.unmounted(upper)
  pressEsc()
  assert.equal(lower.clicks, 1, 'после закрытия верхнего Esc не дошёл до нижнего')
  vDialog.unmounted(lower)
})

test('нажатие, уже обработанное внутри окна, окно не закрывает', () => {
  const d = fakeDialog('поиск')
  vDialog.mounted(d)
  pressEsc(true)
  assert.equal(d.clicks, 0)
  vDialog.unmounted(d)
})

test('нет открытых окон — Esc никого не ловит, слушатель снят', () => {
  const d = fakeDialog('x')
  vDialog.mounted(d)
  vDialog.unmounted(d)
  assert.equal((listeners.keydown || new Set()).size, 0, 'слушатель Esc остался после закрытия')
})

test('topDialog пропускает окна, уже снятые со страницы', () => {
  const a = { isConnected: true }
  const b = { isConnected: false }
  assert.equal(topDialog([a, b]), a)
  assert.equal(topDialog([]), null)
})

// ── Окна на страницах — тоже под директивой ──────────────────────────────────────────
const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const MODAL = /<div\b(?![^>]*\bv-dialog\b)[^>]*class="fixed inset-0 z-[^"]*"[^>]*@click\.self=/g

function* vueFiles(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* vueFiles(p)
    else if (name.endsWith('.vue')) yield p
  }
}

/** Затемнённые окна с «щелчком мимо» без v-dialog. */
function modalsWithoutDirective(text) {
  return [...text.matchAll(MODAL)].map((m) => m[0])
    .filter((tag) => /bg-black\/|--gb-overlay/.test(tag))
}

test('каждое затемнённое окно страницы — под v-dialog', () => {
  const bad = []
  for (const p of vueFiles(join(SRC, 'pages'))) {
    const found = modalsWithoutDirective(readFileSync(p, 'utf8').replace(/\r\n/g, '\n'))
    if (found.length) bad.push(`${p}: ${found.length}`)
  }
  assert.deepEqual(bad, [])
})

test('обратный ход: окно Аттестации без директивы находится', () => {
  const p = join(SRC, 'pages/teacher/TeacherJournal.vue')
  const text = readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
  const broken = text.replace('<div v-dialog v-if="showAtt"', '<div v-if="showAtt"')
  assert.notEqual(broken, text)
  assert.equal(modalsWithoutDirective(broken).length, 1)
})

test('окно подтверждения не ловит Esc само — иначе две отмены на одно нажатие', () => {
  const text = readFileSync(join(SRC, 'components/ui/ConfirmDialog.vue'), 'utf8')
  assert.doesNotMatch(text, /addEventListener\('keydown'/)
})

// ── Страница под окном не реагирует на Esc (нашёл Полковник 02.10.2026) ─────────────────
// «Настройки» и колесо активностей ловят Esc на window РАНЬШЕ директивы: Esc в «Сеансах»
// закрывал и окно, и сами Настройки (router.back()).
test('hasOpenDialog знает, открыто ли окно', () => {
  assert.equal(hasOpenDialog(), false)
  const d = fakeDialog('сеансы')
  vDialog.mounted(d)
  assert.equal(hasOpenDialog(), true)
  vDialog.unmounted(d)
  assert.equal(hasOpenDialog(), false)
})

for (const rel of ['pages/Settings.vue', 'components/activity/ActivityLauncher.vue']) {
  test(`${rel}: Esc страницы молчит, пока открыто окно`, () => {
    const text = readFileSync(join(SRC, rel), 'utf8')
    const at = text.search(/function on(Esc|Key)\(e\)/)
    assert.ok(at >= 0)
    assert.match(text.slice(at, at + 260), /hasOpenDialog\(\)/, 'обработчик не спрашивает про окно')
  })
}
