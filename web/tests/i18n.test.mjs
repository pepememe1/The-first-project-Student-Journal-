// i18n.test.mjs — согласованность словарей интерфейса.
//
// Проверяется не «правильно ли переведено» (это человеческая работа), а то, что ломается
// молча и видно только на живом экране: ключ есть в одном языке и забыт в другом, ключ
// используется в разметке, но его нет в словаре, в переводе остался русский текст.
//
// Ключи в коде ищутся по исходникам: список «где какой ключ нужен» вручную разъедется с
// разметкой на первой же правке.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

function readDict() {
  const text = readFileSync(join(SRC, 'i18n/dictionaries.js'), 'utf8')
  const out = {}
  for (const lang of ['ru', 'en', 'zh']) {
    const start = text.indexOf(`\n  ${lang}: {`)
    assert.ok(start > 0, `в словаре нет языка ${lang}`)
    const body = text.slice(start, text.indexOf('\n  },', start))
    out[lang] = new Set([...body.matchAll(/'([\w.]+)':/g)].map((m) => m[1]))
  }
  return out
}

function walk(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, acc)
    else if (/\.(vue|js)$/.test(name)) acc.push(full)
  }
  return acc
}

const dict = readDict()

test('в каждом языке один и тот же набор ключей', () => {
  // Забытый ключ — это не «непереведённая строка», а вопрос доверия: человек видит
  // интерфейс, где половина подписей на его языке, а половина нет, и решает, что
  // перевод сломан. Русский остаётся источником правды.
  for (const lang of ['en', 'zh']) {
    const missing = [...dict.ru].filter((k) => !dict[lang].has(k))
    const extra = [...dict[lang]].filter((k) => !dict.ru.has(k))
    assert.deepEqual(missing, [], `нет перевода на ${lang}: ${missing.join(', ')}`)
    assert.deepEqual(extra, [], `лишние ключи в ${lang}: ${extra.join(', ')}`)
  }
})

test('каждый ключ из разметки есть в словаре', () => {
  // Ключ без словаря показывает сам себя («login.submit» вместо кнопки) — выглядит
  // как поломка. Ищем ВСЕ обращения t('...') по исходникам.
  const used = new Set()
  for (const file of walk(SRC)) {
    if (file.includes('i18n')) continue
    const text = readFileSync(file, 'utf8')
    for (const m of text.matchAll(/\b(?:loc\.)?t\(\s*'([\w.]+)'/g)) used.add(m[1])
  }
  const unknown = [...used].filter((k) => !dict.ru.has(k))
  assert.deepEqual(unknown, [], `ключи используются, но их нет в словаре: ${unknown.join(', ')}`)
})

test('в английском и китайском не осталось кириллицы', () => {
  // Самая частая ошибка при пополнении словаря — скопировать русскую строку в чужой
  // блок и забыть перевести. На экране это неотличимо от «перевод не применился».
  const text = readFileSync(join(SRC, 'i18n/dictionaries.js'), 'utf8')
  for (const lang of ['en', 'zh']) {
    const start = text.indexOf(`\n  ${lang}: {`)
    const body = text.slice(start, text.indexOf('\n  },', start))
    for (const [, key, value] of body.matchAll(/'([\w.]+)':\s*'([^']*)'/g)) {
      assert.ok(!/[а-яёА-ЯЁ]/.test(value),
        `${lang}.${key} осталось на русском: «${value}»`)
    }
  }
})

test('пункты меню переводимы или честно остаются русскими', () => {
  // У пункта меню либо есть ключ i18n, либо он показывается по-русски — но никогда
  // не пустым. Проверяем, что все проставленные ключи существуют.
  const nav = readFileSync(join(SRC, 'config/nav.js'), 'utf8')
  const keys = [...nav.matchAll(/i18n:\s*'([\w.]+)'/g)].map((m) => m[1])
  assert.ok(keys.length > 10, 'в меню почти нет ключей перевода — правка не применилась')
  const unknown = keys.filter((k) => !dict.ru.has(k))
  assert.deepEqual(unknown, [], `в меню ключи без словаря: ${unknown.join(', ')}`)
})

test('коды языков совпадают с теми, что принимает сервер', () => {
  // Сервер чистит prefs.locale по своему списку. Разъедутся — выбранный язык молча
  // не сохранится, и человек будет выставлять его при каждом входе.
  const text = readFileSync(join(SRC, 'i18n/dictionaries.js'), 'utf8')
  const codes = [...text.matchAll(/code:\s*'(\w+)'/g)].map((m) => m[1]).sort()
  const me = readFileSync(join(SRC, '../../server/app/routers/me.py'), 'utf8')
  const server = [...me.match(/_UI_LOCALES = \(([^)]*)\)/)[1].matchAll(/"(\w+)"/g)]
    .map((m) => m[1]).sort()
  assert.deepEqual(codes, server, 'списки языков клиента и сервера разошлись')
})
