// Сторож: шрифт, названный в коде, обязан быть у нас на диске.
//
// ⚠️ Повод не гипотетический. Пасхалки просили пиксельный шрифт, в пяти компонентах
// стояло `font-family: 'Press Start 2P'` — а файла не было вовсе. Браузер молча берёт
// следующий в стеке (monospace), то есть в коде шрифт «есть», в сборке «есть», а на
// экране его нет и никогда не было. Ни сборка, ни линтер такого не видят.
//
// ⚠️ Ссылка на fonts.googleapis.com тоже не годится и потому проверяется отдельно:
// внутри программы интернета может не быть, а из CSP боевого Caddy этот хост убран
// (152-ФЗ, §3.6) — то есть на бою она гарантированно не сработает.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'

// ⚠️ Только fileURLToPath: `new URL(...).pathname` на Windows даёт «/C:/…», и обход
// каталога падает, не проверив НИЧЕГО (уже наступали, см. localeInterpolation.test.mjs).
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..', 'src')
const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), '..', 'public')

// ⚠️ Разрешённые НЕхостящиеся имена — только с причиной, и причина обязана быть про
// то, что вид НЕ НЕСЁТ СМЫСЛА. Разница между этим списком и настоящей ошибкой не в
// разметке (у обоих есть запасной `monospace`), а в замысле: код в чате одинаково
// читается любым моноширинным, а пиксельная шутка без пиксельного шрифта — не шутка.
// Добавляешь сюда имя — значит сознательно говоришь «запасной шрифт меня устроит».
const FALLBACK_OK = new Map([
  ['JetBrains Mono', 'код в сообщениях: стоит у человека — красиво, нет — обычный моноширинный'],
])

// Общесистемные стеки — их не хостят и хостить не надо.
const SYSTEM = new Set(['monospace', 'sans-serif', 'serif', 'system-ui', 'ui-monospace',
  'inherit', 'cursive', 'fantasy', 'ui-sans-serif', 'ui-serif', 'Arial', 'Georgia',
  'Times New Roman', 'Courier New', 'Segoe UI', 'Helvetica', 'Helvetica Neue'])

function walk(dir, out = []) {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (/\.(vue|css|js)$/.test(e.name)) out.push(p)
  }
  return out
}

const files = walk(SRC)
const css = files.filter(f => f.endsWith('style.css')).map(f => readFileSync(f, 'utf8')).join('\n')
const declared = new Set([...css.matchAll(/font-family:\s*'([^']+)'/g)]
  .filter(m => css.slice(0, m.index).lastIndexOf('@font-face') > css.slice(0, m.index).lastIndexOf('}'))
  .map(m => m[1]))

test('каждый именованный шрифт объявлен через @font-face', () => {
  const missing = []
  for (const f of files) {
    const text = readFileSync(f, 'utf8')
    for (const m of text.matchAll(/font-family:\s*'([^']+)'/g)) {
      const name = m[1]
      if (SYSTEM.has(name) || declared.has(name) || FALLBACK_OK.has(name)) continue
      // Переменные темы (var(--gb-font)) сюда не попадают — они без кавычек.
      missing.push(`${f.slice(SRC.length + 1)}: '${name}'`)
    }
  }
  assert.deepEqual(missing, [], 'шрифт назван, но не объявлен @font-face:\n' + missing.join('\n'))
})

test('файл каждого объявленного шрифта реально лежит в public', () => {
  const missing = []
  for (const m of css.matchAll(/url\('(\/fonts\/[^']+)'\)/g)) {
    if (!existsSync(join(PUBLIC, m[1]))) missing.push(m[1])
  }
  assert.deepEqual(missing, [], 'в @font-face указан несуществующий файл:\n' + missing.join('\n'))
})

// ⚠️ Комментарии выбрасываем ДО проверки: сторож, ругающийся на объяснение «почему мы
// НЕ ходим в Google», обесценивает себя с первого дня — ровно так уже вышло со сторожем
// вёрстки и с ownUserId.test.mjs.
const stripComments = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

test('шрифты не тянутся с Google — из CSP боевого Caddy этот хост убран', () => {
  const bad = files.filter(f => /fonts\.(googleapis|gstatic)\.com/.test(stripComments(readFileSync(f, 'utf8'))))
  assert.deepEqual(bad.map(f => f.slice(SRC.length + 1)), [])
})

// Обратный ход: правило обязано срабатывать на дословной строке, из-за которой оно и
// заведено. Без этого сторож неотличим от исправного кода.
test('обратный ход: несуществующий шрифт и живая ссылка на Google ловятся', () => {
  assert.ok(!declared.has('Pixelify Sans'), 'шрифта без кириллицы у нас нет и быть не должно')
  assert.match("font-family: 'Press Start 2P'", /font-family:\s*'([^']+)'/)
  assert.ok(/fonts\.googleapis\.com/.test(stripComments("@import url(https://fonts.googleapis.com/css2)")),
    'живая ссылка обязана попадаться под правило')
  assert.ok(!/fonts\.googleapis\.com/.test(stripComments('/* не ходим в fonts.googleapis.com */')),
    'а упоминание в комментарии — нет')
})
