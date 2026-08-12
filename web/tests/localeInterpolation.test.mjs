// localeInterpolation.test.mjs — сторож на подстановку в переводах.
//
// 🔥 ЗАЧЕМ. `t()` в этом проекте принимает ДВА аргумента: `t(key, paramsOrFallback)`.
// Второй — либо объект параметров, либо строка-фолбэк, но НЕ то и другое сразу.
// Вызов `t('offline.pending', 'не отправлено: {n}', { n: 3 })` выглядит совершенно
// естественно (так устроены многие библиотеки i18n), молча проходит сборку и линтер —
// и показывает человеку буквальное «не отправлено: {n}». Ровно это и уехало на телефон.
//
// Ошибка незаметна вдвойне: на языке разработки строка чаще всего берётся из словаря, а
// не из фолбэка, поэтому в коде видно правильный текст, а на экране — фигурные скобки.
//
// Проверяем ровно две вещи, обе определяются по разметке однозначно:
//   1) нет вызовов `t()` с тремя аргументами;
//   2) ключ, в тексте которого есть подстановка `{…}`, не вызывается БЕЗ объекта.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// ⚠️ fileURLToPath, а НЕ .pathname: на Windows последний даёт «/C:/…», и join
// склеивает «C:\C:\…» — тест падает на несуществующем пути, не проверив ничего.
const SRC = fileURLToPath(new URL('../src/', import.meta.url))
const DICT = fileURLToPath(new URL('../src/i18n/dictionaries.js', import.meta.url))

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(vue|js)$/.test(name)) out.push(full)
  }
  return out
}

/** Ключи русского словаря, в тексте которых есть подстановка вида {n}. */
function keysWithPlaceholders() {
  const raw = readFileSync(DICT, 'utf8')
  const ru = raw.slice(raw.indexOf('ru: {'), raw.indexOf('en: {'))
  const out = new Set()
  for (const m of ru.matchAll(/'([\w.]+)':\s*'((?:[^'\\]|\\.)*)'/g)) {
    if (/\{[a-zA-Z_][\w]*\}/.test(m[2])) out.add(m[1])
  }
  return out
}

const FILES = walk(SRC).filter((f) => !f.endsWith('dictionaries.js'))

test('нет вызовов t() с тремя аргументами', () => {
  // `t('key', 'фолбэк', { … })` — третий аргумент просто отбрасывается, и подстановка
  // не срабатывает. Ищем строковый литерал ключа, за ним строковый фолбэк, за ним ещё
  // запятую: этого достаточно, чтобы поймать форму, и не задевает `t(key, { … })`.
  const bad = []
  for (const f of FILES) {
    const src = readFileSync(f, 'utf8')
    for (const m of src.matchAll(/\bt\(\s*'[\w.]+'\s*,\s*'(?:[^'\\]|\\.)*'\s*,/g)) {
      const line = src.slice(0, m.index).split('\n').length
      bad.push(`${f.replace(SRC, '')}:${line}`)
    }
  }
  assert.deepEqual(bad, [], `t() принимает два аргумента, третий теряется:\n${bad.join('\n')}`)
})

test('ключ с подстановкой не вызывается без параметров', () => {
  const needParams = keysWithPlaceholders()
  assert.ok(needParams.size > 5, 'словарь разобран неверно — ключей с подстановкой почти нет')

  const bad = []
  for (const f of FILES) {
    const src = readFileSync(f, 'utf8')
    for (const m of src.matchAll(/\bt\(\s*'([\w.]+)'\s*([,)])/g)) {
      if (!needParams.has(m[1])) continue
      // За ключом должен идти ОБЪЕКТ. Закрывающая скобка или строка-фолбэк означают,
      // что подставлять нечем и человек увидит фигурные скобки.
      const after = src.slice(m.index + m[0].length - 1)
      const ok = m[2] === ',' && /^\s*,\s*\{/.test(after)
      if (!ok) {
        const line = src.slice(0, m.index).split('\n').length
        bad.push(`${f.replace(SRC, '')}:${line}  ${m[1]}`)
      }
    }
  }
  assert.deepEqual(bad, [], `подстановка не сработает, на экране будут «{}»:\n${bad.join('\n')}`)
})

test('сторож действительно срабатывает на дословной строке, вызвавшей баг', () => {
  // Без этого теста правило могло бы не ловить ничего и выглядеть исправным — та же
  // ловушка, что уже была со сторожем вёрстки (регулярка не совпадала ни разу).
  const broken = "locale.t('offline.pending', 'не отправлено: {n}', { n: pendingCount })"
  const rule = /\bt\(\s*'[\w.]+'\s*,\s*'(?:[^'\\]|\\.)*'\s*,/
  assert.ok(rule.test(broken), 'правило обязано ловить именно ту форму, что уехала на телефон')

  const fixed = "locale.t('offline.pending', { n: pendingCount })"
  assert.ok(!rule.test(fixed), 'и не должно ругаться на правильную форму')
})
