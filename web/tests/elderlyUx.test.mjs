// elderlyUx.test.mjs — удобство для преподавателя 55–65 лет на телефоне (живой прогон
// 23.10.2026: Galaxy S24, учётка преподавателя, режим слабовидящих и font_scale 1.3).
//
// Проверяется проводка найденного: кнопки шапки, меню и входа не меньше 44 dp на
// сенсорном экране; выбранное в высоком контрасте не тусклее невыбранного; «Войти» не
// серая при пустом поле; флажок, меняющий данные группы, спрашивает подтверждение;
// у списков журнала есть подписи. Компоненты в node не поднять, поэтому — разбор
// исходников; у каждой проверки есть обратный ход.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const TAG = /<(button|RouterLink|a)\b(?:\s+[^\s"'=<>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'))?)*\s*\/?>/g

/** Кнопки размером 24–36 px без увеличения на сенсорном экране. */
function smallTouchTargets(src) {
  const out = []
  for (const m of src.matchAll(TAG)) {
    const t = m[0]
    if (/(?<![\w:-])(?:size|h)-[6-9](?![\w-])/.test(t) && !t.includes('pointer-coarse:')) {
      out.push(t.replace(/\s+/g, ' ').slice(0, 100))
    }
  }
  return out
}

//Шапка, меню и вход — то, чего пальцем касаются в каждом сеансе.
const CHROME = ['../src/components/HeaderBar.vue', '../src/components/Sidebar.vue',
  '../src/components/SidebarUserPanel.vue', '../src/components/AccessibilityMenu.vue',
  '../src/pages/LoginPage.vue']

test('в шапке, меню и на входе нет мелких кнопок без увеличения для пальца', () => {
  for (const f of CHROME) assert.deepEqual(smallTouchTargets(read(f)), [], f)
})

test('обратный ход: мелкая кнопка без pointer-coarse находится', () => {
  const src = read('../src/components/SidebarUserPanel.vue').replace(/ pointer-coarse:size-11/, '')
  assert.equal(smallTouchTargets(src).length, 1)
})

const CSS = read('../src/style.css')

function filledInBothContrastBlocks(css) {
  const manual = /html\.gb-contrast :is\(a, button\)\.bg-accent-glow \{ background-color: var\(--gb-accent\) !important; \}/.test(css)
  const media = css.slice(css.indexOf('@media (prefers-contrast: more)'))
  const system = /\n {2}:is\(a, button\)\.bg-accent-glow \{ background-color: var\(--gb-accent\) !important; \}/.test(media)
  //Голый «.bg-accent-glow {» заливал и баннеры со своей зелёной кнопкой внутри (Полковник 23.10.2026).
  const bare = /(^|\n)\s*(html\.gb-contrast )?\.bg-accent-glow[ ,{]/.test(css)
  return manual && system && !bare
}

test('высокий контраст: выбранное — сплошной заливкой в обоих блоках-близнецах', () => {
  assert.equal(filledInBothContrastBlocks(CSS), true)
})

test('обратный ход: правило только в одном блоке находится', () => {
  const broken = CSS.replace(/\n {2}:is\(a, button\)\.bg-accent-glow \{ background-color: var\(--gb-accent\) !important; \}/, '')
  assert.notEqual(broken, CSS)
  assert.equal(filledInBothContrastBlocks(broken), false)
  //И заливка всего подряд, а не только кнопок и ссылок.
  const wide = CSS.replace('html.gb-contrast :is(a, button).bg-accent-glow {', 'html.gb-contrast .bg-accent-glow {')
  assert.notEqual(wide, CSS)
  assert.equal(filledInBothContrastBlocks(wide), false)
})

test('панель очков: ширина из развёрнутого ref, а не `.value` в шаблоне', () => {
  //В шаблоне <script setup> ref уже развёрнут: `menuW.value` давало «undefinedpx», и
  //панель не росла со шрифтом (Полковник 23.10.2026).
  const src = read('../src/components/AccessibilityMenu.vue')
  const tpl = src.slice(src.indexOf('<template>'))
  assert.match(tpl, /width: menuW \+ 'px'/)
  assert.doesNotMatch(tpl, /menuW\.value/)
})

test('вход: подсказка пароля словами, «Войти» не серая из-за пустого поля', () => {
  const login = read('../src/pages/LoginPage.vue')
  assert.doesNotMatch(login, /placeholder="•+"/, 'точки в пустом поле читаются как введённый пароль')
  assert.match(login, /<AppButton type="submit" class="w-full" :disabled="auth\.loading">/)
  assert.match(login, /emptyHint\.value = field === 'login'/)
})

test('флажок раздельного обучения спрашивает подтверждение до изменения', () => {
  const src = read('../src/pages/teacher/CuratorView.vue')
  const body = src.slice(src.indexOf('async function toggleSplit('), src.indexOf('function openSubgroups('))
  const ask = body.indexOf('await confirm(')
  const write = body.indexOf('curatorApi.setSubjectSplit(')
  assert.ok(ask > 0 && ask < write, 'изменение уходит на сервер без вопроса')
  assert.match(body, /if \(!ok\) \{ if \(box\) box\.checked = !on; return \}/)
  //И при отказе сервера: состояние не изменилось, Vue отметку сам не вернёт.
  const caught = body.slice(body.indexOf('} catch (e) {'))
  assert.match(caught, /if \(box\) box\.checked = !on/)
})

test('журнал: подписи над списками, при пустой нагрузке списков нет, легенда в rem', () => {
  const src = read('../src/pages/teacher/TeacherJournal.vue')
  assert.match(src, /teacherJournal\.groupLabel/)
  assert.match(src, /teacherJournal\.subjectLabel/)
  assert.match(src, /<template v-if="groups\.length && subjects\.length">/)
  assert.doesNotMatch(src, /gap-y-1 text-tiny text-text3/, 'легенда в px не растёт в режиме слабовидящих')
})
