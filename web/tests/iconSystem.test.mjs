// iconSystem.test.mjs — один значок на одно действие и никаких эмодзи вместо значков.
//
// Интерфейс один на сайт, программу и телефон, и визуальная память держится на том, что
// одно действие везде выглядит одинаково. До 27.10.2026 кнопки местами были эмодзи —
// каждая система рисует их по-своему (флаги на Windows выходили буквами, «⬟» не было в
// шрифте вовсе), — а «обновить» и «назад» были сделаны двумя разными значками.
// Сторож смотрит свойство по всему web/src, а не список поправленных мест: новое место
// с эмодзи или синонимом покраснеет само.
//
// Эмодзи остаются там, где они — содержимое, а не значок: реакции и быстрые ответы
// уходят текстом сообщения, подсказка «так держать» — голос Вектора. Их рисует свой
// шрифт Twemoji одинаково везде. Пасхалки (components/easter) — сцены по мотивам игр.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import { ICONS, FORBIDDEN_SYNONYMS } from '../src/config/icons.js'

const SRC = fileURLToPath(new URL('../src', import.meta.url))

// Строки, где эмодзи — содержимое. Признак — подстрока строки, а не целый файл:
// разрешение на файл пропустило бы и новую кнопку-эмодзи рядом.
const CONTENT_EMOJI = [
  'const REACTIONS = [',            // реакции на сообщение
  'chatThread.quick.accepted',      // быстрый ответ уходит текстом сообщения
  'studentDashboard.tipGoodDefault', // подсказка голосом Вектора
]

// Эмодзи и символы, которыми рисовали кнопки. ©, ® и ™ — типографика, а не значок.
const ICONISH = /(?![©®™])[\p{Extended_Pictographic}✕✎]/u

function sources(dir = SRC, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (name !== 'easter') sources(p, out)
    } else if (/\.(vue|js)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

function code(path) {
  return readFileSync(path, 'utf8')
    .replace(/\r\n/g, '\n')
    .replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ''))
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ''))
    .split('\n')
    .map((l) => l.replace(/(^|[^:'"`\w])\/\/.*$/, '$1'))
}

const rel = (p) => relative(SRC, p).split(sep).join('/')

test('в интерфейсе нет эмодзи вместо значков', () => {
  const found = []
  for (const p of sources()) {
    code(p).forEach((line, i) => {
      if (ICONISH.test(line) && !CONTENT_EMOJI.some((s) => line.includes(s))) {
        found.push(`${rel(p)}:${i + 1}: ${line.trim().slice(0, 100)}`)
      }
    })
  }
  assert.deepEqual(found, [], 'значок берётся из словаря: <GbIcon name="…" /> (config/icons.js)')
})

test('значки-синонимы lucide не импортируются и не упоминаются в разметке', () => {
  // Не только импорт: 27.10.2026 замена поправила импорт, а `:is="… : CheckCircle2"` в
  // разметке осталась — значок молча пропал бы со страницы. Имя в одинарных кавычках —
  // строка JS (например, клавиша), а не компонент.
  const found = []
  const IMPORT = /import\s*\{([^}]*)\}\s*from\s*'@lucide\/vue'/g
  const TOKEN = new RegExp(`(?<![\\w'])(${Object.keys(FORBIDDEN_SYNONYMS).join('|')})(?![\\w'])`)
  for (const p of sources()) {
    if (rel(p) === 'config/icons.js') continue
    const text = readFileSync(p, 'utf8')
    for (const m of text.matchAll(IMPORT)) {
      for (const raw of m[1].split(',')) {
        const name = raw.trim().split(/\s+as\s+/)[0]
        if (name in FORBIDDEN_SYNONYMS) found.push(`${rel(p)}: ${name} → ICONS.${FORBIDDEN_SYNONYMS[name]}`)
      }
    }
    code(p).forEach((line, i) => {
      const m = line.match(TOKEN)
      if (m && !line.includes("from '@lucide/vue'")) found.push(`${rel(p)}:${i + 1}: ${m[1]}`)
    })
  }
  assert.deepEqual(found, [])
})

test('каждое имя словаря значков указывает на настоящий значок', () => {
  for (const [name, icon] of Object.entries(ICONS)) {
    assert.ok(icon && (typeof icon === 'function' || typeof icon === 'object'), `ICONS.${name} пуст`)
  }
})

test('GbIcon зовут только именами из словаря', () => {
  // Неизвестное имя GbIcon молча рисует знак вопроса — опечатку видно только глазами.
  const unknown = []
  for (const p of sources()) {
    const text = readFileSync(p, 'utf8')
    for (const m of text.matchAll(/<GbIcon\b([^>]*)>/g)) {
      const attrs = m[1]
      const names = []
      const stat = attrs.match(/(?<![:\w-])name="(\w+)"/)
      if (stat) names.push(stat[1])
      const dyn = attrs.match(/:name="([^"]*)"/)
      if (dyn) names.push(...[...dyn[1].matchAll(/'(\w+)'/g)].map((x) => x[1]))
      for (const n of names) if (!(n in ICONS)) unknown.push(`${rel(p)}: ${n}`)
    }
  }
  assert.deepEqual(unknown, [])
})
