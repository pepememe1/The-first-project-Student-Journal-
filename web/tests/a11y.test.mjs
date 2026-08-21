/**
 * a11y.test.mjs — сторож режима для слабовидящих (stores/a11y.js).
 *
 * ━━ ЗАЧЕМ ━━
 * Вся фича держится на ОДНОЙ строке: `useA11yStore().apply()` в main.js раскладывает
 * сохранённую настройку в DOM ДО монтирования. Уберёшь её — крупный шрифт и контраст
 * молча перестанут применяться при загрузке (сработают лишь после первого тыка в меню,
 * который сам зовёт apply()). Ни сборка, ни линтер этого не увидят: строка синтаксически
 * не нужна никому, а её отсутствие — не ошибка, а тихая потеря поведения. Это наш самый
 * частый класс дефекта — «обещание без вызывающего» (см. CLAUDE.md). Поэтому проверяем
 * ВЫЗОВ, а не поведение стора.
 *
 * Заодно держим CSS-обвязку: масштаб работает только через `--gb-font-scale` на <html>,
 * контраст — только через класс `gb-contrast`. Вырежут любое — фича станет пустой галочкой.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const SRC = fileURLToPath(new URL('../src', import.meta.url))
const read = (p) => readFileSync(join(SRC, p), 'utf8')

// Строка без комментария, реально вызывающая apply() у стора доступности.
const APPLY_CALL = /^\s*useA11yStore\(\)\.apply\(\)/m

test('main.js применяет режим слабовидящих ДО монтирования (вызывающий на месте)', () => {
  const main = read('main.js')
  assert.match(main, /useA11yStore/,
    'main.js обязан импортировать стор доступности')
  assert.match(main, APPLY_CALL,
    'main.js обязан звать useA11yStore().apply() — иначе сохранённая крупность/контраст '
    + 'не применятся при загрузке страницы (тихая потеря поведения, сборка молчит).')
  // Вызов должен стоять ДО app.mount, иначе первый кадр — обычный, и интерфейс дёргается.
  assert.ok(main.indexOf('useA11yStore().apply()') < main.indexOf('app.mount('),
    'apply() режима слабовидящих должен идти до app.mount(#app)')
})

// ⚠️ Обратный ход: без него сторож не отличить от сломанного. Правило обязано СРАБОТАТЬ
// на живой строке и МОЛЧАТЬ на её комментарии/отсутствии.
test('правило вызова точно ловит строку и не путает её с комментарием', () => {
  assert.match('useA11yStore().apply()', APPLY_CALL)
  assert.doesNotMatch('// useA11yStore().apply() — раньше стояло здесь', APPLY_CALL)
  assert.doesNotMatch('const theme = useThemeStore()', APPLY_CALL)
})

test('CSS-обвязка на месте: масштаб через --gb-font-scale и класс контраста gb-contrast', () => {
  const css = read('style.css')
  // Масштаб приложен к КОРНЮ (<html>), иначе rem-текст Tailwind не растёт.
  assert.match(css, /html\s*\{[^}]*font-size:\s*calc\(100%\s*\*\s*var\(--gb-font-scale/,
    'html { font-size: calc(100% * var(--gb-font-scale…)) } — двигатель крупности')
  // Высокий контраст поднимает приглушённый текст до полного через utility-классы.
  assert.match(css, /html\.gb-contrast\s+\.text-text3\s*\{[^}]*var\(--gb-text\)/,
    'правило высокого контраста для .text-text3 должно существовать')
})
