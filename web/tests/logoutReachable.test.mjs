// logoutReachable.test.mjs — к выходу из аккаунта ведёт дорога с карточки себя (28.09.2026).
//
// Живой прогон десктопа: тестировщик не нашёл «Выйти» вовсе — кнопка живёт в самом низу
// раздела «Аккаунт» настроек (намеренно: случайный клик в углу экрана не должен выкидывать
// из журнала). Карточка себя в сайдбаре теперь ведёт К ЭТОЙ кнопке, а не выходит сама.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const SRC = join(dirname(dirname(fileURLToPath(import.meta.url))), 'src')
const overlay = readFileSync(join(SRC, 'components', 'SidebarUserOverlay.vue'), 'utf8')
const settings = readFileSync(join(SRC, 'pages', 'Settings.vue'), 'utf8')

test('карточка себя ведёт к выходу в настройках, а не выходит сама', () => {
  assert.match(overlay, /settings\?section=logout/, 'в карточке себя нет дороги к выходу')
  assert.doesNotMatch(overlay, /auth\.logout\(/, 'карточка выходит сама — мимо проверки неотправленного')
})

test('настройки понимают ?section=logout и якорь существует', () => {
  assert.match(settings, /section[^\n]*=== 'logout'[^\n]*goSub\('account', 'logout'\)/)
  assert.match(settings, /<Card id="set-logout"/, 'нет карточки, к которой ведёт якорь')
})
