// bottomNav.test.mjs — нижняя панель телефона и то, что к ней привязано (23.10.2026, §4.51).
//
// Что держится:
//   • вкладки роли — пункты её же меню (`NAV`), не больше четырёх плюс «Меню»;
//   • оболочка показывает панель, прячет её в открытой беседе и при наборе текста и
//     убирает верхнюю кнопку «Меню», когда панель есть;
//   • профиль, статус и счётчик уведомлений грузит оболочка, а не карточка в шторке —
//     иначе на телефоне до первого открытия меню не было аватарки (ddxd, 23.10.2026);
//   • всё, что прижато к нижнему краю, поднимается над панелью (`--gb-bottom-chrome`);
//   • пояснения к «Риску» и «Переводу на курс» стоят на месте и не врут о порогах.
//
// ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `profile.load()` в SidebarUserPanel и убрать из
// оболочки — краснеет «одна дверь»; вернуть `bottom-4` тосту — краснеет «поднято над
// панелью»; поменять 65 на 60 в `dropout_risk.py` — краснеет «пороги».
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { NAV, TABS, TAB_LABELS, isNavActive, tabsFor } from '../src/config/nav.js'
import { MESSAGES as messages } from '../src/i18n/dictionaries.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'src')
const read = (p) => readFileSync(join(SRC, p), 'utf8')

test('вкладки каждой роли — пункты её меню, не больше четырёх', () => {
  assert.deepEqual(Object.keys(TABS).sort(), Object.keys(NAV).sort(),
    'у роли нет нижней панели — на телефоне она снова только с «Меню» в углу')
  for (const [role, keys] of Object.entries(TABS)) {
    assert.ok(keys.length >= 2 && keys.length <= 4, `${role}: ${keys.length} вкладок + «Меню»`)
    const items = tabsFor(role)
    assert.equal(items.length, keys.length, `${role}: ключа нет в NAV — вкладка пропала молча`)
    for (const it of items) {
      assert.ok(it.to && it.icon, `${role}/${it.key}: без адреса или значка`)
      assert.ok(!it.curatorOnly && !it.phoneOnly, `${role}/${it.key}: пункт виден не всем`)
    }
  }
})

test('короткие подписи вкладок есть во всех языках', () => {
  for (const [key, fallback] of Object.values(TAB_LABELS)) {
    for (const lang of Object.keys(messages)) {
      assert.ok(messages[lang][key], `${lang}: нет ${key} (${fallback})`)
    }
  }
})

test('главная роли подсвечена только сама, раздел — со своими страницами', () => {
  assert.equal(isNavActive('/teacher', '/teacher'), true)
  assert.equal(isNavActive('/teacher', '/teacher/schedule'), false)
  assert.equal(isNavActive('/teacher/messages', '/teacher/messages/x'), true)
  assert.equal(isNavActive('/teacher/messages', '/teacher/messagesx'), false)
})

test('оболочка показывает панель и прячет её в беседе и при наборе', () => {
  const shell = read('layouts/AppShell.vue')
  assert.match(shell, /<BottomNav v-if="tabbarShown"/)
  assert.match(shell, /const tabbarShown = computed\(\(\) => tabbar\.value && !chatOpen\.value && !typing\.value\)/)
  assert.match(shell, /const tabbar = computed\(\(\) => !embed && !isLg\.value\)/)
  assert.match(shell, /<HeaderBar[^>]*:menu-button="!tabbar"/)
  assert.match(read('components/HeaderBar.vue'), /<button v-if="menuButton"/)
})

test('профиль, статус и значок уведомлений грузит оболочка — одна дверь', () => {
  const shell = read('layouts/AppShell.vue')
  for (const call of ['profile.load()', 'messenger.loadMyStatus()', 'messenger.startIdleWatch()',
    'navBadges.start()']) {
    assert.ok(shell.includes(call), `оболочка не зовёт ${call}`)
  }
  const panel = read('components/SidebarUserPanel.vue').replace(/\/\/.*$/gm, '')
  assert.ok(!/profile\.load\(|startIdleWatch\(/.test(panel),
    'карточка в шторке снова грузит профиль сама — вторая дверь')
  assert.ok(!/unreadCount\(/.test(read('components/Sidebar.vue')),
    'меню снова опрашивает уведомления само — на телефоне без шторки значок не живёт')
  //Выход — смена владельца телефона: и обычный, и сброс сессии обнуляют чужое число.
  const auth = read('stores/auth.js').replace(/\/\/.*$/gm, '')
  assert.equal((auth.match(/useNavBadgesStore\(\)\.reset\(\)/g) || []).length, 2,
    'счётчик уведомлений прежнего человека переживает выход')
})

function walk(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? walk(p) : (p.endsWith('.vue') ? [p] : [])
  })
}

// Прижатые к низу, которым панель не мешает, — с причиной. Остальные обязаны подниматься.
const BOTTOM_OK = {
  'components/easter/FnafOffice.vue': 'подпись внутри сцены на весь экран, панель под сценой',
  'components/easter/FarCryQuote.vue': 'цитата на несколько секунд поверх всего, кликов не ждёт',
  'components/easter/StanleyNarrator.vue': 'субтитр в процентах высоты, кликов не ждёт',
  'components/messenger/ChatThread.vue': 'в открытой беседе панели нет',
  'components/messenger/PeerProfileCard.vue': 'лист поверх затемнения, закрывает и панель',
}

test('всё, что прижато к нижнему краю, поднято над панелью', () => {
  const bad = []
  for (const file of walk(SRC)) {
    const rel = relative(SRC, file).replaceAll('\\', '/')
    const src = readFileSync(file, 'utf8')
    for (const m of src.matchAll(/class="([^"]*\bfixed\b[^"]*)"/g)) {
      const cls = m[1]
      if (!/(^|\s)bottom-/.test(cls) || /\binset-0\b/.test(cls)) continue
      if (cls.includes('--gb-bottom-chrome') || BOTTOM_OK[rel]) continue
      bad.push(`${rel}: ${cls.slice(0, 80)}`)
    }
  }
  assert.deepEqual(bad, [], 'ляжет на вкладки нижней панели')
})

test('высоты полноэкранных страниц считают нижнюю панель', () => {
  const css = read('style.css')
  assert.match(css, /--gb-page-offset: calc\([^;]*var\(--gb-bottom-chrome\)\)/)
  assert.match(css, /--gb-chrome-offset: calc\([^;]*var\(--gb-bottom-chrome\)\)/)
  const lg = css.match(/--breakpoint-lg:\s*(\d+)px/)[1]
  assert.match(css, new RegExp(`@media \\(min-width: ${lg}px\\) \\{\\s*:root \\{\\s*--gb-page-offset`),
    'граница «мобильной полосы» в формуле высоты разошлась с lg оболочки')
  assert.match(read('components/BottomNav.vue'), /setProperty\('--gb-bottom-chrome'/)
})

test('пояснения к риску и переводу на курс стоят на месте', () => {
  const curator = read('pages/teacher/CuratorView.vue')
  assert.match(curator, /<TabExplainer :lead="locale\.t\('curatorView\.riskLead'/)
  assert.match(curator, /<TabExplainer :lead="locale\.t\('curatorView\.zetLead'/)
  assert.ok(!/наведите/i.test(messages.ru['curatorView.riskMore'] + messages.ru['curatorView.riskLead']),
    'подсказка снова про наведение — на телефоне наводить нечем')
  const badge = read('components/ui/RiskBadge.vue')
  assert.match(badge, /:aria-expanded="canOpen \? open : null"/, 'причины риска снова только при наведении')
})

test('пороги в пояснении риска совпадают с dropout_risk.py', () => {
  const py = readFileSync(join(ROOT, '..', 'dropout_risk.py'), 'utf8')
  const edges = [...py.matchAll(/^\s*\((\d+), "(low|medium|high|critical)"/gm)].map((m) => m[1])
  const minVisible = py.match(/^MIN_VISIBLE = (\d+)/m)[1]
  assert.equal(edges.length, 4)
  const text = messages.ru['curatorView.riskMore']
  for (const n of [...edges, minVisible]) {
    assert.ok(new RegExp(`(от|ниже) ${n}\\b`).test(text), `в пояснении нет порога ${n}`)
  }
  assert.equal(read('pages/teacher/CuratorView.vue').includes(text.replaceAll('\n', '\\n')), true,
    'запасной русский текст в CuratorView разошёлся со словарём')
})
