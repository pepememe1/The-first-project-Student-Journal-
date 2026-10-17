// indexBootContent.test.mjs — у главной есть содержимое БЕЗ скрипта (17.10.2026).
//
// Google Search Console сообщил, что сайт не индексируется. Главная «/» — единственная
// открытая краулеру страница приложения, а её тело было пустым `<div id="app">`: всё
// рисует скрипт из /assets/, закрытого в robots.txt. Поисковик видел страницу без слов.
//
// ⚠️ Проверяем ТЕКСТ файла, а не браузер: Playwright исполняет скрипт и увидел бы
// нарисованную страницу входа, то есть был бы зелёным при пустом HTML.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
const html = readFileSync(join(WEB, 'index.html'), 'utf8')
const robots = readFileSync(join(WEB, 'public', 'robots.txt'), 'utf8')
const allows = robots
  .split(/\r?\n/)
  .filter((l) => /^Allow:/i.test(l.trim()))
  .map((l) => l.split(':')[1].trim())

const noComments = (s) => s.replace(/<!--[\s\S]*?-->/g, '')

/** Содержимое `<div id="app">` до скрипта модуля — то, что видит краулер без JS. */
export function appBlock(src) {
  const m = noComments(src).match(/<div id="app">([\s\S]*?)<\/div>\s*<script/)
  return m ? m[1] : ''
}

const textOf = (s) => s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

/** Открыта ли ссылка краулеру: `/$` — только сама главная, остальное — по префиксу. */
function allowed(href) {
  return allows.some((a) => (a === '/$' ? href === '/' : href.startsWith(a)))
}

test('у главной без скрипта есть заголовок и описание', () => {
  const block = appBlock(html)
  const h1 = block.match(/<h1[^>]*>([\s\S]*?)<\/h1>/)
  assert.ok(h1 && textOf(h1[1]).length >= 20, 'в #app нет заголовка — поисковик видит пустую страницу')
  assert.ok(textOf(block).length >= 150, 'в #app слишком мало текста, чтобы страницу было за что индексировать')
})

test('ссылки заставки ведут только на открытые в robots.txt страницы', () => {
  const hrefs = [...appBlock(html).matchAll(/href="([^"]+)"/g)].map((m) => m[1])
  assert.ok(hrefs.length > 0, 'на заставке нет ни одной ссылки на документы')
  for (const h of hrefs) {
    assert.ok(allowed(h), `ссылка ${h} ведёт на закрытый в robots.txt адрес — поисковик запишет её в «заблокировано»`)
  }
})

test('/assets/ закрыт для краулера намеренно', () => {
  // Со скриптом роутер уводит гостя с «/» на /login, а /login закрыт: открыв /assets/,
  // мы показали бы поисковику переадресацию на запрещённый адрес вместо страницы.
  assert.ok(!allows.some((a) => a.startsWith('/assets')),
    'robots.txt открыл /assets/ — главная превратится для поисковика в переадресацию на /login')
})

test('встроенные стили заставки не трогают html, body и :root', () => {
  // Стили вне слоёв сильнее `@layer base` приложения: правило `body { background }` здесь
  // перебило бы тему после запуска, и тёмная тема рисовалась бы на светлом фоне.
  const styles = [...noComments(html).matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1])
  for (const css of styles) {
    const selectors = [...css.matchAll(/(^|})\s*([^{}]+)\{/g)].map((m) => m[2].trim())
    for (const sel of selectors) {
      assert.ok(!/(^|[\s,])(html|body|:root)\b/.test(sel), `встроенный стиль «${sel}» переопределит тему приложения`)
    }
  }
})

test('обратный ход: пустой #app проверка видит пустым', () => {
  assert.equal(textOf(appBlock('<div id="app"></div>\n<script type="module" src="/x.js"></script>')), '')
  assert.equal(appBlock('<div id="app"><!-- <h1>только комментарий</h1> --></div><script>'), '')
})
