// Сторож: граница «телефонной» раскладки задана в ДВУХ местах и обязана совпадать.
//
// ⚠️ Разметка переключается CSS-ом (`lg:` → `--breakpoint-lg`), а логика оболочки —
// медиазапросом в JS. Разъедутся на сколько угодно — появится полоса ширины, где
// сайдбар уже нарисован, а код всё ещё считает нас телефоном (или наоборот: шторка
// открыта поверх постоянного сайдбара). Ошибка видна только на конкретной ширине окна,
// то есть почти никогда — и именно поэтому её надо ловить тестом.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const css = readFileSync(join(ROOT, 'src/style.css'), 'utf8')
const shell = readFileSync(join(ROOT, 'src/layouts/AppShell.vue'), 'utf8')

test('CSS и JS используют одно и то же число', () => {
  const fromCss = css.match(/--breakpoint-lg:\s*(\d+)px/)
  assert.ok(fromCss, 'в style.css нет --breakpoint-lg — граница снова стандартная')
  const fromJs = shell.match(/const LG_PX = (\d+)/)
  assert.ok(fromJs, 'в AppShell нет LG_PX')
  assert.equal(fromJs[1], fromCss[1],
    `CSS переключается на ${fromCss[1]}px, а логика на ${fromJs[1]}px`)
})

test('в оболочке не осталось зашитых пикселей мимо LG_PX', () => {
  // Именно так и было до правки: два `matchMedia('(min-width:1024px)')` литералами.
  const literals = [...shell.matchAll(/matchMedia\(\s*['"]\(min-width:\s*(\d+)px/g)]
  assert.deepEqual(literals.map((m) => m[1]), [],
    'медиазапрос с зашитым числом — он не изменится вместе с границей')
})

test('граница честна по отношению к телефонам', () => {
  // Самый широкий телефон в альбомной ориентации — около 930 px. Граница ниже этого
  // числа означала бы, что телефон показывает настольную раскладку; сильно выше — что
  // половина монитора показывает телефонную (ровно на это и жаловались).
  const px = Number(css.match(/--breakpoint-lg:\s*(\d+)px/)[1])
  assert.ok(px >= 930, `граница ${px}px ниже самого широкого телефона`)
  assert.ok(px <= 1000, `граница ${px}px слишком высока — половина монитора станет телефоном`)
})

test('меню слабовидящих не зависит от размера шрифта', () => {
  // 🔥 Оно САМО увеличивает шрифт — и, будучи шириной в `rem`, разъезжалось вместе с
  // ним и уезжало за левый край экрана вместе с кнопкой «вернуть обычный вид». То есть
  // режим для слабовидящих ломал ровно тот элемент, которым из него выходят.
  const src = readFileSync(join(ROOT, 'src/components/AccessibilityMenu.vue'), 'utf8')
  // ⚠️ Прежняя регулярка требовала, чтобы `rounded-xl` шёл ПОСЛЕ закрывающей кавычки
  // атрибута, а в настоящем коде `w-60` и `rounded-xl` лежали в ОДНОМ `class`. Она не
  // срабатывала на том самом коде, ради которого написана (нашёл Полковник) — ровно тот
  // класс, что уже записан в инвариантах: «регулярка ждала пробел, а там кавычка».
  // Теперь смотрим проще и вернее: есть ли ширина в единицах шрифта в КЛАССЕ всплывающей
  // панели. Проверка вместе с обратным ходом ниже.
  const popupClass = (src.match(/class="([^"]*rounded-xl[^"]*bg-card[^"]*)"/) || [])[1] || ''
  assert.ok(popupClass, 'не нашёл класс всплывающей панели — разбор сломался')
  assert.ok(!/\bw-\d+\b/.test(popupClass),
    `ширина меню снова задана в единицах шрифта: ${popupClass}`)
  assert.match(src, /const MENU_W = \d+/, 'нет ширины в пикселях')
  assert.match(src, /getBoundingClientRect/, 'положение не считается по факту')
  assert.match(src, /window\.innerWidth/, 'меню не прижимается к границе окна')
})

test('обратный ход: проверка ширины ловит ДОСЛОВНУЮ прежнюю разметку', () => {
  // Строка взята из файла ДО правки. Если правило её не ловит — оно не защищает ни от
  // чего, и это ровно тот случай, который Полковник нашёл в первой версии.
  const OLD = '<div v-if="open"\n'
    + '     class="absolute z-50 w-60 rounded-xl border border-border2 bg-card p-3 shadow-card"'
  const popupClass = (OLD.match(/class="([^"]*rounded-xl[^"]*bg-card[^"]*)"/) || [])[1] || ''
  assert.ok(popupClass, 'разбор не нашёл класс в прежней разметке')
  assert.ok(/\bw-\d+\b/.test(popupClass),
    'правило НЕ видит ширину в единицах шрифта в прежней разметке — оно бесполезно')
})
