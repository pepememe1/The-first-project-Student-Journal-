// achievements.test.mjs — справочник ачивок на клиенте и белый список на сервере
// обязаны совпадать ПОИМЁННО.
//
// ━━ ЗАЧЕМ ЭТОТ СТОРОЖ ━━
// Справочник намеренно разрезан пополам: сервер хранит только идентификаторы (ему
// нужен белый список, чтобы в публичную витрину профиля нельзя было протащить
// произвольную строку), а названия, значки и редкость живут на клиенте, где
// переводятся вместе с интерфейсом. Разрез удобен, но у него есть цена: две половины
// могут разъехаться, и разъедутся они МОЛЧА.
//
// Что будет при расхождении: новая ачивка есть на клиенте, но её id сервер не знает —
// `unlock()` тихо откажет и запишет строку в лог, которую никто не читает. Человек
// найдёт пасхалку и не получит за неё ничего. Обратный случай не лучше: id есть на
// сервере, но нет в справочнике — витрина отдаст его чужому профилю, а нарисовать
// карточку будет нечем, и трофей просто исчезнет из списка.
//
// Обратный ход ПРОВЕРЕН: удаление любой строки из ACHIEVEMENTS красит первую проверку,
// удаление из питоновского словаря — вторую.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { ACHIEVEMENTS, BY_ID, RARITY } from '../src/config/achievements.js'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')

// Читаем именно ПИТОНОВСКИЙ файл, а не свою копию списка: копия рядом с проверкой
// сверяла бы саму себя и была бы зелёной при любом расхождении.
function serverIds() {
  const src = readFileSync(resolve(root, 'server/app/easter_eggs.py'), 'utf-8')
  const block = src.split('ACHIEVEMENTS: dict[str, str] = {')[1].split('}')[0]
  return new Set([...block.matchAll(/^\s*"([\w]+)":/gm)].map((m) => m[1]))
}

test('каждая ачивка клиента известна серверу', () => {
  const server = serverIds()
  assert.ok(server.size > 0, 'белый список сервера не разобрался — проверка ничего не проверяет')
  const missing = ACHIEVEMENTS.map((a) => a.id).filter((id) => !server.has(id))
  assert.deepEqual(missing, [],
    'сервер не знает эти id — unlock() тихо откажет, и человек не получит ачивку')
})

test('каждая ачивка сервера есть в справочнике клиента', () => {
  const extra = [...serverIds()].filter((id) => !BY_ID[id])
  assert.deepEqual(extra, [],
    'нечем нарисовать карточку — трофей молча исчезнет из витрины чужого профиля')
})

test('у каждой ачивки заполнены значок, название и известная редкость', () => {
  for (const a of ACHIEVEMENTS) {
    assert.ok(a.icon, `${a.id}: нет значка`)
    assert.ok(a.title && a.title.length > 2, `${a.id}: нет названия`)
    assert.ok(a.desc && a.desc.length > 5, `${a.id}: нет описания`)
    assert.ok(RARITY[a.rarity], `${a.id}: неизвестная редкость «${a.rarity}»`)
  }
})

test('идентификаторы не повторяются', () => {
  const ids = ACHIEVEMENTS.map((a) => a.id)
  assert.equal(new Set(ids).size, ids.length, 'дубль id — одна карточка перекроет другую')
})
